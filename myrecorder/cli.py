"""Recovery and experimental speed conversion, usable without Qt."""
import argparse
import json
from pathlib import Path
import struct
from .media import assemble, convert
from .settings import storage_directory


def repair_wav(path):
    # Our own PCM WAV writer always creates a standard 44-byte header.
    size = path.stat().st_size
    with path.open('r+b') as f:
        header = f.read(44)
        if len(header) != 44 or header[:4] != b'RIFF' or header[36:40] != b'data':
            raise ValueError(f'지원하지 않는 WAV 헤더: {path}')
        if size - 8 > 0xffffffff:
            raise ValueError('4GB 이상 WAV는 자동 복구할 수 없습니다.')
        f.seek(4)
        f.write(struct.pack('<I', size - 8))
        f.seek(40)
        f.write(struct.pack('<I', size - 44))


def main():
    parser = argparse.ArgumentParser(description='MyRecorder 복구 / 실험용 변환')
    sub = parser.add_subparsers(dest='command', required=True)
    recovery = sub.add_parser('recover')
    recovery.add_argument('session', type=Path)
    recovery.add_argument('--output', type=Path, required=True)
    speed = sub.add_parser('convert')
    speed.add_argument('source', type=Path)
    speed.add_argument('--temp', type=Path, help='생략하면 settings.json의 temp 폴더 사용')
    speed.add_argument('--output', type=Path, help='생략하면 settings.json의 converted 폴더 사용')
    speed.add_argument('--recorded-speed', type=float, required=True)
    speed.add_argument('--output-speed', type=float, default=1.0)
    args = parser.parse_args()
    if args.command == 'recover':
        args.output = storage_directory(args.output)
        args.session = storage_directory(args.session)
        manifest_path = args.session / 'session.json'
        data = json.loads(manifest_path.read_text(encoding='utf-8'))
        for segment in data['segments']:
            for track in segment['tracks']:
                repair_wav(args.session / track['file'])
        print(assemble(args.session.resolve(), args.output.resolve(), data['title'] + '_복구'))
    else:
        print(convert(args.source.resolve(), args.recorded_speed, args.output_speed, args.output, args.temp))


if __name__ == '__main__':
    main()
