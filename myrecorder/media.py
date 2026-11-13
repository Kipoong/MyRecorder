from __future__ import annotations
import json
import errno
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
from .settings import storage_directory, SettingsStore

CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def binary(name: str) -> str:
    roots = [Path(sys.executable).parent, Path(getattr(sys, '_MEIPASS', Path(__file__).parent.parent)) / 'bin', Path(__file__).parent.parent / 'bin']
    for root in roots:
        candidate = root / (name + '.exe' if os.name == 'nt' else name)
        if candidate.is_file():
            return str(candidate)
    found = shutil.which(name)
    if not found:
        raise RuntimeError(f'{name}을 찾을 수 없습니다. bin 폴더 또는 PATH에 설치하세요.')
    return found


def run(args: list[str]) -> None:
    result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', errors='replace')[-6000:])


def safe_title(title: str) -> str:
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', title).strip().rstrip('. ')
    title = title[:100].rstrip('. ') or '녹화'
    if title.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *('COM'+str(i) for i in range(1,10)), *('LPT'+str(i) for i in range(1,10))}:
        title = '_' + title
    return title


def publish(temp: Path, folder: Path, title: str) -> Path:
    """Exclusive reservation prevents overwrite, even with concurrent instances."""
    folder.mkdir(parents=True, exist_ok=True)
    title = safe_title(title)
    n = 0
    while True:
        dest = folder / f'{title}{f" ({n})" if n else ""}.mp4'
        try:
            fd = os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            n += 1
    try:
        try:
            os.replace(temp, dest)
        except OSError as exc:
            if exc.errno != errno.EXDEV and getattr(exc, 'winerror', None) != 17:
                raise
            # Across user-selected drives: stage only the final copy at destination.
            staging = folder / f'.myrecorder-publish-{uuid.uuid4().hex}.partial'
            try:
                with temp.open('rb') as src, staging.open('xb') as target:
                    shutil.copyfileobj(src, target, length=1024 * 1024)
                    target.flush()
                    os.fsync(target.fileno())
                os.replace(staging, dest)
                temp.unlink()
            finally:
                staging.unlink(missing_ok=True)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return dest


def probe(path: Path) -> dict:
    result = subprocess.run([binary('ffprobe'), '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                            capture_output=True, creationflags=CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace'))
    data = json.loads(result.stdout)
    if not any(s['codec_type'] == 'video' for s in data['streams']):
        raise RuntimeError('영상 스트림이 없습니다.')
    return data


def mux_segment(folder: Path, index: int, tracks: list[dict]) -> Path:
    video = folder / f'{index:04d}.mkv'
    out = folder / f'{index:04d}-ready.mp4'
    args = [binary('ffmpeg'), '-y', '-i', str(video)]
    filters = []
    for i, track in enumerate(tracks, 1):
        args += ['-i', str(folder / track['file'])]
        delay = max(0, round(track['offset'] * 1000))
        filters.append(f'[{i}:a]aresample=async=1,adelay={delay}:all=1,apad[a{i}]')
    if tracks:
        labels = ''.join(f'[a{i}]' for i in range(1, len(tracks)+1))
        filters.append(f'{labels}amix=inputs={len(tracks)}:duration=longest:normalize=1[a]')
        args += ['-filter_complex', ';'.join(filters), '-map', '0:v:0', '-map', '[a]', '-c:a', 'aac', '-b:a', '192k', '-shortest']
    else:
        args += ['-map', '0:v:0', '-an']
    args += ['-c:v', 'copy', '-movflags', '+faststart', str(out)]
    run(args)
    probe(out)
    return out


def assemble(folder: Path, destination: Path, title: str) -> Path:
    folder = storage_directory(folder)
    destination = storage_directory(destination)
    manifest = json.loads((folder / 'session.json').read_text(encoding='utf-8'))
    ready = []
    for segment in manifest['segments']:
        if segment.get('usable') is False:
            continue
        ready.append(mux_segment(folder, segment['index'], segment['tracks']))
    if not ready:
        raise RuntimeError('저장할 녹화 구간이 없습니다.')
    # ASCII relative filenames avoid FFmpeg concat quoting problems in Korean paths.
    listing = folder / 'concat.txt'
    listing.write_text(''.join(f"file '{p.name}'\n" for p in ready), encoding='utf-8')
    temp = folder / f'.myrecorder-{uuid.uuid4().hex}.mp4'
    try:
        run([binary('ffmpeg'), '-y', '-f', 'concat', '-safe', '0', '-i', str(listing), '-c', 'copy', '-movflags', '+faststart', str(temp)])
        probe(temp)
        return publish(temp, destination, title)
    finally:
        temp.unlink(missing_ok=True)


def convert(source: Path, recorded_speed: float, output_speed: float = 1.0, destination: Path | None = None, temp_folder: Path | None = None) -> Path:
    if recorded_speed not in (1, 1.25, 1.5, 1.75, 2) or output_speed not in (1, 1.25, 1.5, 1.75, 2):
        raise ValueError('지원하지 않는 배속입니다.')
    defaults = SettingsStore().load() if destination is None or temp_folder is None else None
    destination = storage_directory(destination if destination is not None else defaults.converted)
    temp_folder = storage_directory(temp_folder if temp_folder is not None else defaults.temp)
    data = probe(source)
    factor = recorded_speed / output_speed
    temp = temp_folder / f'.convert-{uuid.uuid4().hex}.mp4'
    args = [binary('ffmpeg'), '-y', '-i', str(source), '-vf', f'setpts={factor}*(PTS-STARTPTS)', '-map', '0:v:0', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p']
    if any(s['codec_type'] == 'audio' for s in data['streams']):
        args += ['-map', '0:a:0', '-af', f'atempo={1/factor}', '-c:a', 'aac', '-b:a', '192k']
    args += ['-movflags', '+faststart', str(temp)]
    try:
        run(args)
        converted = probe(temp)
        expected = float(data['format']['duration']) * factor
        if abs(float(converted['format']['duration']) - expected) > max(0.5, expected * 0.01):
            raise RuntimeError('변환 길이 검증 실패. 원본은 보존되었습니다.')
        return publish(temp, destination, source.stem + f'_{output_speed:g}배속')
    finally:
        temp.unlink(missing_ok=True)
