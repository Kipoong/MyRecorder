"""Manual-only window title/OCR recognition. Does not access browser internals."""
from __future__ import annotations
from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess
from .media import safe_title, CREATE_NO_WINDOW


class TitleError(RuntimeError):
    pass


@dataclass(frozen=True)
class LectureWindow:
    hwnd: int
    title: str
    pid: int


def normalize_title(raw: str) -> str:
    text = re.sub(r'\s+', ' ', raw).strip()
    if not re.sub(r'[<>:"/\\|?*\x00-\x1f. ]', '', text):
        raise TitleError('인식한 제목이 비어 있습니다. 기존 제목을 유지합니다.')
    return safe_title(text)


def _api():
    if os.name != 'nt':
        raise TitleError('창 제목 인식은 Windows에서 지원됩니다.')
    import ctypes
    from ctypes import wintypes
    api = ctypes.WinDLL('user32', use_last_error=True)
    api.GetForegroundWindow.argtypes = []
    api.GetForegroundWindow.restype = wintypes.HWND
    api.IsWindow.argtypes = [wintypes.HWND]
    api.IsWindow.restype = wintypes.BOOL
    api.IsWindowVisible.argtypes = [wintypes.HWND]
    api.IsWindowVisible.restype = wintypes.BOOL
    api.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    api.GetWindowTextLengthW.restype = ctypes.c_int
    api.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    api.GetWindowTextW.restype = ctypes.c_int
    api.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    api.GetWindowThreadProcessId.restype = wintypes.DWORD
    return api


def _read_window(api, hwnd):
    import ctypes
    from ctypes import wintypes
    if not hwnd or not api.IsWindow(hwnd) or not api.IsWindowVisible(hwnd):
        return None
    pid = wintypes.DWORD()
    api.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == os.getpid():
        return None
    length = min(api.GetWindowTextLengthW(hwnd), 8192)
    if length < 1:
        return None
    buffer = ctypes.create_unicode_buffer(length+1)
    if not api.GetWindowTextW(hwnd, buffer, len(buffer)):
        return None
    title = buffer.value.strip()
    return LectureWindow(int(hwnd), title, pid.value) if title else None


def foreground_window():
    api = _api()
    return _read_window(api, api.GetForegroundWindow())


def list_windows():
    import ctypes
    from ctypes import wintypes
    api = _api()
    windows = []
    errors = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collect(hwnd, parameter):
        try:
            item = _read_window(api, hwnd)
            if item: windows.append(item)
            return True
        except Exception as exc:
            errors.append(str(exc))
            return False
    callback = callback_type(collect)
    api.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    api.EnumWindows.restype = wintypes.BOOL
    if not api.EnumWindows(callback, 0) or errors:
        raise TitleError('창 목록을 읽지 못했습니다. 새로고침 후 다시 선택하세요.')
    return windows


def window_title(hwnd: int) -> str:
    item = _read_window(_api(), hwnd)
    if item is None:
        raise TitleError('선택한 창이 닫혔거나 제목을 읽을 수 없습니다. 창 목록을 새로고침하세요.')
    return normalize_title(item.title)


def tesseract_path(explicit=None):
    if explicit:
        path = Path(explicit)
        if path.is_file(): return str(path)
        raise TitleError('지정한 OCR 실행 파일을 찾을 수 없습니다.')
    candidates = [Path(__file__).resolve().parent.parent/'bin'/'tesseract'/'tesseract.exe']
    for env in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
        root = os.environ.get(env)
        if root:
            candidates += [Path(root)/'Tesseract-OCR'/'tesseract.exe', Path(root)/'Programs'/'Tesseract-OCR'/'tesseract.exe']
    found = shutil.which('tesseract')
    if found: return found
    for candidate in candidates:
        if candidate.is_file(): return str(candidate)
    raise TitleError('OCR에는 별도 Tesseract와 언어 데이터가 필요합니다. 설치 후 OCR 엔진 선택에서 tesseract.exe를 지정하세요. 창 제목 인식은 OCR 없이 사용할 수 있습니다.')


def ocr_title(png: bytes, language='kor+eng', executable=None) -> str:
    if language not in ('kor+eng', 'kor', 'eng'):
        raise TitleError('지원하지 않는 OCR 언어입니다.')
    if not png:
        raise TitleError('OCR 화면 이미지를 가져오지 못했습니다.')
    engine = tesseract_path(executable)
    try:
        langs = subprocess.run([engine, '--list-langs'], stdin=subprocess.DEVNULL,
            capture_output=True, timeout=10, creationflags=CREATE_NO_WINDOW)
        available = set(line.strip() for line in langs.stdout.decode('utf-8', errors='replace').splitlines())
        if langs.returncode or not set(language.split('+')).issubset(available):
            raise TitleError(f'OCR 언어 데이터 {language}를 사용할 수 없습니다. Tesseract의 kor/eng 데이터를 설치하거나 OCR 언어를 변경하세요.')
        result = subprocess.run([engine, 'stdin', 'stdout', '-l', language, '--psm', '6'], input=png,
            capture_output=True, timeout=30, creationflags=CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired as exc:
        raise TitleError('OCR 실행 시간이 초과되었습니다. 영역을 작게 선택한 뒤 다시 실행하세요.') from exc
    except OSError as exc:
        raise TitleError('OCR 실행 파일을 시작하지 못했습니다. 설치 위치와 필요한 DLL을 확인하세요.') from exc
    if result.returncode:
        raise TitleError('OCR 엔진이 이미지를 처리하지 못했습니다. 언어 데이터와 선택 영역을 확인하세요.')
    return normalize_title(result.stdout.decode('utf-8', errors='replace'))
