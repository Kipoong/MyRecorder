"""Portable configuration and explicit media storage policy; never fall back to cwd."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import json
import ntpath
import os
from pathlib import Path, PureWindowsPath
import sys
import tempfile


class StorageError(ValueError):
    pass


def application_root() -> Path:
    override = os.environ.get('MYRECORDER_HOME')
    if override:
        root = Path(override)
        if not root.is_absolute():
            raise StorageError('MYRECORDER_HOME은 절대 경로여야 합니다.')
        return root.resolve()
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).resolve().parent
        for root in (exe_dir, *exe_dir.parents):
            if (root / 'myrecorder.project.json').is_file():
                return root
        return exe_dir
    return Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class StoragePaths:
    recordings: str = r'F:\MyRecorder\Recordings'
    converted: str = r'F:\MyRecorder\Converted'
    temp: str = r'F:\MyRecorder\Temp'


LABELS = {'recordings': '녹화 저장 폴더', 'converted': '변환 영상 폴더', 'temp': '임시 녹화 폴더'}


def check_windows_path(raw: str, development: str) -> None:
    """Pure path checks also testable on Linux; resolve junctions separately at runtime."""
    p = PureWindowsPath(raw)
    if not p.is_absolute() or str(p).startswith(('\\\\?\\', '\\\\.\\')):
        raise StorageError('드라이브 또는 UNC 공유를 포함한 일반 절대 경로를 선택하세요.')
    if any(part.casefold().startswith('onedrive') for part in p.parts):
        raise StorageError('영상과 임시 파일은 OneDrive 안에 저장할 수 없습니다.')
    normalized = ntpath.normcase(ntpath.normpath(raw))
    dev = ntpath.normcase(ntpath.normpath(development))
    try:
        if ntpath.commonpath([normalized, dev]) == dev:
            raise StorageError('개발 폴더 안에는 영상과 임시 파일을 저장할 수 없습니다.')
    except ValueError as exc:
        if isinstance(exc, StorageError):
            raise
        # Different drives cannot contain each other.


def check_windows_drive(raw: str, available=None) -> None:
    available = available or os.path.isdir
    anchor = str(PureWindowsPath(raw).anchor)
    if not anchor or not available(anchor):
        raise StorageError(f'드라이브 또는 공유에 접근할 수 없습니다: {anchor}. 다른 경로를 직접 선택하세요.')


def storage_directory(raw: str | Path, development: Path | None = None) -> Path:
    raw = str(raw)
    dev = (development or application_root()).resolve()
    if not raw.strip():
        raise StorageError('빈 경로는 사용할 수 없습니다. 저장 폴더를 선택하세요.')
    if os.name == 'nt':
        check_windows_path(raw, str(dev))
        check_windows_drive(raw)
    elif PureWindowsPath(raw).drive:
        raise StorageError('Windows 저장 경로는 Windows PC에서만 확인할 수 있습니다.')
    path = Path(raw)
    if not path.is_absolute():
        raise StorageError('상대 경로는 사용할 수 없습니다. 절대 경로를 선택하세요.')
    try:
        resolved = path.resolve()
        if resolved == dev or dev in resolved.parents:
            raise StorageError('개발 폴더 안에는 영상과 임시 파일을 저장할 수 없습니다.')
        if any(p.casefold().startswith('onedrive') for p in resolved.parts):
            raise StorageError('OneDrive 경로에는 영상과 임시 파일을 저장할 수 없습니다.')
        for key, value in os.environ.items():
            if key.casefold().startswith('onedrive') and value:
                cloud = Path(value).resolve()
                if resolved == cloud or cloud in resolved.parents:
                    raise StorageError('OneDrive 동기화 폴더에는 저장할 수 없습니다.')
        # Check the root before mkdir: do not create local folders resembling a missing drive.
        if not Path(resolved.anchor).is_dir():
            raise StorageError(f'드라이브 또는 공유에 접근할 수 없습니다: {resolved.anchor}')
        resolved.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix='.myrecorder-write-test-', dir=resolved) as handle:
            handle.write(b'MyRecorder')
            handle.flush()
            os.fsync(handle.fileno())
        return resolved
    except (OSError, RuntimeError) as exc:
        raise StorageError(f'폴더를 생성하거나 쓸 수 없습니다: {path}\n{exc}') from exc


def prepare_storage(paths: StoragePaths, development: Path | None = None) -> dict[str, Path]:
    resolved = {}
    errors = []
    for key, value in asdict(paths).items():
        try:
            resolved[key] = storage_directory(value, development)
        except StorageError as exc:
            errors.append(f'{LABELS[key]}: {value}\n{exc}')
    if errors:
        raise StorageError('\n\n'.join(errors) + '\n\n자동 대체 경로는 사용하지 않습니다. 설정에서 다른 폴더를 선택하세요.')
    if len(set(resolved.values())) != 3:
        raise StorageError('녹화·변환·임시 폴더는 서로 다른 경로로 지정하세요.')
    return resolved


class SettingsStore:
    def __init__(self, root: Path | None = None):
        self.root = (root or application_root()).resolve()
        self.path = self.root / 'settings.json'

    def load(self) -> StoragePaths:
        if not self.path.exists():
            paths = StoragePaths()
            self.save(paths)
            return paths
        try:
            data = json.loads(self.path.read_text(encoding='utf-8-sig'))
            if not isinstance(data, dict):
                raise ValueError('설정의 최상위 값은 JSON 객체여야 합니다.')
            if data.get('version') != 1:
                raise ValueError('지원하지 않는 설정 버전')
            values = data['storage']
            if set(values) != set(LABELS) or any(not isinstance(v, str) or not v.strip() for v in values.values()):
                raise ValueError('storage의 recordings, converted, temp 문자열이 필요합니다.')
            return StoragePaths(**values)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise StorageError(f'설정 파일을 읽을 수 없습니다: {self.path}\n{exc}\n기존 파일을 보존한 뒤 settings.example.json을 참고하여 수정하세요.') from exc

    def save(self, paths: StoragePaths):
        # No implicit media creation here: saving defaults must work even without F:.
        staging = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.root,
                                             prefix='.settings-', suffix='.tmp', delete=False) as f:
                staging = Path(f.name)
                json.dump({'version': 1, 'storage': asdict(paths)}, f, ensure_ascii=False, indent=2)
                f.write('\n')
                f.flush()
                os.fsync(f.fileno())
            os.replace(staging, self.path)
        except OSError as exc:
            raise StorageError(f'개발 폴더에 설정을 저장할 수 없습니다: {self.path}\n{exc}') from exc
        finally:
            if staging:
                staging.unlink(missing_ok=True)
