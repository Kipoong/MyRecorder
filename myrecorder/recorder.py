from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json
import os
import subprocess
import time
import uuid
from .audio import AudioTrack, Diagnostics
from .settings import StoragePaths, prepare_storage
from .media import binary, CREATE_NO_WINDOW, assemble


@dataclass
class Options:
    folder: Path
    title: str
    rect: tuple[int, int, int, int]
    temp_folder: Path = Path(r'F:\MyRecorder\Temp')
    converted_folder: Path = Path(r'F:\MyRecorder\Converted')
    fps: int = 30
    crf: int = 23
    cursor: bool = True
    system: bool = True
    mic: bool = False
    system_device: dict | None = None


class Recorder:
    def __init__(self, options: Options):
        if os.name != 'nt':
            raise RuntimeError('실제 화면 녹화는 Windows 10/11에서 지원됩니다.')
        self.options = options
        binary('ffprobe')
        directories = prepare_storage(StoragePaths(str(options.folder), str(options.converted_folder), str(options.temp_folder)))
        options.folder = directories['recordings']
        self.folder = directories['temp'] / ('session-' + uuid.uuid4().hex)
        self.folder.mkdir()
        self.diagnostics = Diagnostics(self.folder / 'audio-diagnostics.jsonl')
        self.manifest = {'version': 2, 'title': options.title, 'title_source': 'manual',
                         'recordings_folder': str(options.folder),
                         'converted_folder': str(directories['converted']),
                         'temp_folder': str(directories['temp']), 'segments': [], 'warnings': []}
        self.process = None
        self.audio = []
        self.log = None
        self.segment = None
        self.started = 0.0
        self.elapsed = 0.0
        self.save_manifest()

    def save_manifest(self):
        tmp = self.folder / 'session.tmp'
        with tmp.open('w', encoding='utf-8') as f:
            json.dump(self.manifest, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.folder / 'session.json')

    def start(self):
        index = len(self.manifest['segments'])
        x, y, w, h = self.options.rect
        self.audio = []
        self.segment = {'index': index, 'tracks': [], 'complete': False, 'usable': False}
        self.manifest['segments'].append(self.segment)
        self.save_manifest()
        try:
            for enabled, name, loopback in [(self.options.system, 'system', True), (self.options.mic, 'mic', False)]:
                if enabled:
                    self.audio.append(AudioTrack(self.folder / f'{index:04d}-{name}.wav', loopback,
                        selection=self.options.system_device if loopback else None, log=self.diagnostics))
            self.log = (self.folder / f'{index:04d}-ffmpeg.log').open('wb')
            args = [binary('ffmpeg'), '-y', '-hide_banner', '-loglevel', 'warning', '-f', 'gdigrab', '-framerate', str(self.options.fps), '-draw_mouse', str(int(self.options.cursor)), '-offset_x', str(x), '-offset_y', str(y), '-video_size', f'{w}x{h}', '-i', 'desktop', '-an', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', str(self.options.crf), '-pix_fmt', 'yuv420p', '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2', '-flush_packets', '1', '-cluster_time_limit', '1000', str(self.folder / f'{index:04d}.mkv')]
            self.started = time.monotonic()
            self.process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                            stderr=self.log, creationflags=CREATE_NO_WINDOW)
            # Persist audio filenames before starting so crash recovery can locate WAVs.
            self.segment['tracks'] = [{'file': a.path.name, 'offset': 0.0, 'frames': 0, 'rate': a.rate} for a in self.audio]
            self.save_manifest()
            for audio in self.audio:
                audio.start()
            time.sleep(0.5)
            if self.process.poll() is not None:
                raise RuntimeError('화면 캡처 시작 실패. 구간 FFmpeg 로그를 확인하세요.')
            # Short, bounded first-packet wait; no-packet WASAPI is NOT proof of failure.
            for audio in self.audio:
                audio.wait_ready(timeout=1.0)
            self.segment['tracks'] = [dict(self.track_info(audio), offset=max(0, audio.started-self.started)) for audio in self.audio]
            self.segment['usable'] = True
            self.save_manifest()
        except Exception as exc:
            self.segment['startup_error'] = str(exc)
            self.manifest['warnings'].append(str(exc))
            self.diagnostics.write('segment_start_failed', index=index, error=str(exc))
            try:
                self.pause()
            except Exception as cleanup:
                self.diagnostics.write('cleanup_failed', error=str(cleanup))
            self.save_manifest()
            raise RuntimeError(f'{exc}\n오디오 진단 로그: {self.diagnostics.path}\n임시 세션은 보존되었습니다: {self.folder}') from exc

    @staticmethod
    def track_info(audio):
        return {'file': audio.path.name, 'offset': 0.0,
                'frames': audio.frames, 'received_frames': audio.received_frames, 'rate': audio.rate,
                'channels': audio.channels}

    def pause(self):
        if self.process is None and not self.audio:
            return
        errors = []
        tracks = []
        for audio in self.audio:
            try:
                before = audio.snapshot()
                if before['state'] == 'ERROR': errors.append(before['detail'])
                audio.close()
                if audio.started and self.process is not None:
                    track = self.track_info(audio)
                    track['offset'] = max(0, audio.started-self.started)
                    tracks.append(track)
                    if audio.received_frames == 0:
                        self.manifest['warnings'].append(f'[NO_DATA_TIMEOUT] {audio.path.name}: 오디오 미수신. 무음으로 저장됨. 출력 장치와 로그를 확인하세요.')
                    elif before['state'] in ('SILENT', 'BUFFER_WARNING'):
                        self.manifest['warnings'].append(before['detail'])
                if audio.error: errors.append(audio.error)
            except Exception as exc:
                errors.append(str(exc))
                # Even snapshot failure must not prevent closing the audio device/WAV.
                try: audio.close()
                except Exception as cleanup: errors.append(str(cleanup))
        self.audio = []
        if self.segment is not None:
            self.segment['tracks'] = tracks
        proc = self.process
        try:
            if proc is not None:
                if proc.poll() is None:
                    proc.communicate(b'q\n', timeout=20)
                if proc.returncode:
                    errors.append('FFmpeg 비정상 종료: 구간 로그를 확인하세요.')
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            errors.append('FFmpeg 종료 시간 초과. 임시 구간을 복구하세요.')
        except Exception as exc:
            errors.append(str(exc))
        finally:
            if proc is not None:
                self.elapsed += time.monotonic() - self.started
            self.process = None
            if self.log is not None:
                self.log.close()
                self.log = None
            if self.segment is not None:
                self.segment['complete'] = bool(self.segment['usable']) and not errors
            self.manifest['warnings'].extend(errors)
            self.diagnostics.write('segment_closed', errors=errors, tracks=tracks)
            self.save_manifest()
        if errors:
            raise RuntimeError('\n'.join(errors) + f'\n오디오 진단 로그: {self.diagnostics.path}')

    def health(self):
        if self.process and self.process.poll() is not None:
            return '화면 캡처가 중단되었습니다. 종료하여 임시 파일을 보존하세요.'
        for audio in self.audio:
            state = audio.snapshot()
            if state['state'] == 'ERROR':
                return state['detail'] + f'\n오디오 진단 로그: {self.diagnostics.path}'
        return None

    def audio_status(self):
        states = [audio.snapshot() for audio in self.audio]
        warnings = [s['detail'] for s in states if s['state'] != 'RECEIVING']
        if warnings:
            return ' / '.join(warnings) + f' | 로그: {self.diagnostics.path}'
        return '오디오 수신 중' if states else '시스템 소리·마이크 해제 — 무음 화면 녹화 중'

    def finish(self):
        self.pause()
        return assemble(self.folder, self.options.folder, self.options.title)
