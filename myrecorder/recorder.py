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
from .media import binary, CREATE_NO_WINDOW, assemble, probe, media_timing


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
    title_source: str = 'manual'


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
        self.events = Diagnostics(self.folder / 'recording-events.jsonl')
        self.manifest = {'version': 3, 'owner': 'MyRecorder', 'status': 'created',
                         'title': options.title, 'title_source': options.title_source,
                         'recordings_folder': str(options.folder),
                         'converted_folder': str(directories['converted']),
                         'temp_folder': str(directories['temp']), 'segments': [], 'warnings': []}
        self.process = None
        self.audio = []
        self.log = None
        self.segment = None
        self.started = 0.0
        self.elapsed = 0.0
        self.final_duration = None
        self.stop_requested_at = None
        self.save_manifest()

    def save_manifest(self):
        tmp = self.folder / 'session.tmp'
        with tmp.open('w', encoding='utf-8') as f:
            json.dump(self.manifest, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.folder / 'session.json')

    def start(self):
        if self.process is not None or self.audio:
            raise RuntimeError('이전 녹화 자원이 아직 정리되지 않았습니다. 종료 / 저장을 다시 시도하세요.')
        self.stop_requested_at = None
        index = len(self.manifest['segments'])
        self.events.write('segment_begin', index=index, rect=self.options.rect, fps=self.options.fps,
                          system=self.options.system, microphone=self.options.mic)
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
            self.manifest['status'] = 'recording'
            self.events.write('segment_started', index=index, monotonic=self.started)
            self.save_manifest()
        except Exception as exc:
            self.segment['startup_error'] = str(exc)
            self.manifest['status'] = 'failed'
            self.events.write('start_failed', index=index, error=str(exc))
            self.manifest['warnings'].append(str(exc))
            self.diagnostics.write('segment_start_failed', index=index, error=str(exc))
            try:
                self.pause()
            except Exception as cleanup:
                self.diagnostics.write('cleanup_failed', error=str(cleanup))
            self.manifest['status'] = 'failed'
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
        self.stop_requested_at = time.monotonic()
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
        self.audio = [audio for audio in self.audio if not getattr(audio,'resources_released',True)]
        if self.audio:errors.append('오디오 자원 종료 미확인. 새 녹화를 시작하지 말고 로그를 확인하세요.')
        if self.segment is not None and self.process is not None:
            self.segment['tracks'] = tracks
        proc = self.process
        try:
            if proc is not None:
                if proc.poll() is None:
                    proc.communicate(b'q\n', timeout=20)
                if proc.returncode:
                    errors.append('FFmpeg 비정상 종료: 구간 로그를 확인하세요.')
        except Exception as exc:
            errors.append('FFmpeg 종료 오류: '+str(exc))
            try:
                proc.kill();proc.wait(timeout=5)
            except Exception as cleanup:errors.append('FFmpeg 강제 종료 미확인: '+str(cleanup))
        finally:
            released=proc is None or proc.poll() is not None
            if proc is not None and released:
                stream=getattr(proc,'stdin',None)
                if stream is not None:
                    try:stream.close()
                    except Exception as exc:errors.append(str(exc))
                wall = time.monotonic() - self.started
                try:
                    info = probe(self.folder / f"{self.segment['index']:04d}.mkv")
                    duration = float(info['format']['duration'])
                    if not 0 < duration < float('inf'): raise ValueError('invalid duration')
                    self.segment['duration'] = duration
                    self.elapsed += duration
                except Exception as exc:
                    self.elapsed += wall
                    self.segment['duration_warning'] = str(exc)
                self.segment['wall_elapsed'] = wall
            self.process = None if released else proc
            if not released:errors.append('FFmpeg가 아직 실행 중입니다. 종료를 재시도하세요.')
            if self.log is not None:
                self.log.close()
                self.log = None
            if self.segment is not None:
                self.segment['complete'] = bool(self.segment['usable']) and not errors
            self.manifest['warnings'].extend(errors)
            self.manifest['status'] = 'paused' if not errors else 'failed'
            self.events.write('segment_closed', index=self.segment['index'] if self.segment else None,
                              errors=errors, measured_elapsed=self.elapsed)
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
        try:
            self.pause()
            if self.process is not None or self.audio:
                raise RuntimeError('녹화 자원 정리를 확인하지 못하여 저장을 중단했습니다.')
            result = assemble(self.folder, self.options.folder, self.options.title)
            timing = media_timing(result)
            durations=[segment.get('duration') for segment in self.manifest['segments'] if segment.get('usable')]
            if durations and all(value is not None for value in durations):
                timing['segment_duration_sum']=sum(durations)
                timing['duration_difference']=timing['video_duration']-sum(durations)
                if abs(timing['duration_difference'])>max(0.25,len(durations)/self.options.fps):
                    timing['warnings'].append('구간 합계와 최종 영상 길이가 다릅니다. 원본과 재생 시간을 확인하세요.')
            self.final_duration = timing['video_duration']
            self.manifest['warnings'].extend(timing['warnings'])
            self.manifest['owner'] = 'MyRecorder'
            self.manifest['status'] = 'saved'
            self.manifest['output'] = {'path': str(result), 'size': result.stat().st_size, **timing}
            self.events.write('save_completed', output=str(result), **timing)
            self.save_manifest()
            return result
        except Exception as exc:
            self.manifest['status'] = 'save_failed'
            self.events.write('save_failed', error=str(exc))
            try: self.save_manifest()
            except Exception: pass
            raise RuntimeError(f'{exc}\n원본 세션 보존: {self.folder}\n녹화 로그: {self.events.path}') from exc
