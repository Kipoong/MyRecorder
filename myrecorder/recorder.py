from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json
import os
import subprocess
import time
import uuid
from .audio import AudioTrack
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
        self.segment = {'index': index, 'tracks': [], 'complete': False}
        self.manifest['segments'].append(self.segment)
        self.save_manifest()
        try:
            for enabled, name, loopback in [(self.options.system, 'system', True), (self.options.mic, 'mic', False)]:
                if enabled:
                    self.audio.append(AudioTrack(self.folder / f'{index:04d}-{name}.wav', loopback))
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
            for track, audio in zip(self.segment['tracks'], self.audio):
                if audio.started:
                    track['offset'] = max(0, audio.started - self.started)
            self.save_manifest()
            for audio in self.audio:
                if audio.error or not audio.frames:
                    raise RuntimeError(audio.error or '오디오 데이터가 수신되지 않았습니다. 기본 장치와 권한을 확인하세요.')
            if self.process.poll() is not None:
                raise RuntimeError('화면 캡처 시작 실패. 구간 FFmpeg 로그를 확인하세요.')
        except BaseException:
            self.pause()
            raise

    def pause(self):
        if self.process is None:
            for audio in self.audio:
                audio.close()
            self.audio = []
            return
        errors = []
        self.segment['tracks'] = []
        for audio in self.audio:
            try:
                audio.close()
            except Exception as exc:
                errors.append(str(exc))
            if audio.error:
                errors.append(audio.error)
            if audio.started:
                self.segment['tracks'].append({'file': audio.path.name, 'offset': max(0, audio.started-self.started), 'frames': audio.frames, 'rate': audio.rate})
        self.audio = []
        proc = self.process
        try:
            if proc.poll() is None:
                proc.communicate(b'q\n', timeout=20)
            if proc.returncode:
                errors.append('FFmpeg 비정상 종료: 구간 로그를 확인하세요.')
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            errors.append('FFmpeg 종료 시간 초과. 임시 구간을 복구하세요.')
        finally:
            self.elapsed += time.monotonic() - self.started
            self.process = None
            self.log.close()
            self.segment['complete'] = not errors
            self.manifest['warnings'].extend(errors)
            self.save_manifest()
        if errors:
            raise RuntimeError('\n'.join(errors))

    def health(self):
        if self.process and self.process.poll() is not None:
            return '화면 캡처가 중단되었습니다. 종료하여 임시 파일을 보존하세요.'
        for audio in self.audio:
            if audio.error:
                return audio.error
        return None

    def finish(self):
        self.pause()
        return assemble(self.folder, self.options.folder, self.options.title)
