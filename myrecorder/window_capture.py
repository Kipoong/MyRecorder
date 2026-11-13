"""Exclude only our own top-level overlay from supported Windows capture paths."""
from dataclasses import dataclass
import os

WDA_EXCLUDEFROMCAPTURE = 0x11


@dataclass(frozen=True)
class ExclusionStatus:
    applied: bool
    reason: str
    error_code: int = 0


def _native_api():
    import ctypes
    from ctypes import wintypes
    api=ctypes.WinDLL('user32',use_last_error=True)
    api.IsWindow.argtypes=[wintypes.HWND];api.IsWindow.restype=wintypes.BOOL
    api.GetAncestor.argtypes=[wintypes.HWND,ctypes.c_uint];api.GetAncestor.restype=wintypes.HWND
    api.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    api.GetWindowThreadProcessId.restype=wintypes.DWORD
    api.SetWindowDisplayAffinity.argtypes=[wintypes.HWND,wintypes.DWORD]
    api.SetWindowDisplayAffinity.restype=wintypes.BOOL
    api.GetWindowDisplayAffinity.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    api.GetWindowDisplayAffinity.restype=wintypes.BOOL
    return api


def exclude_overlay(hwnd, api=None):
    import ctypes
    from ctypes import wintypes
    if api is None and os.name!='nt':
        return ExclusionStatus(False,'Windows 영상 제외 API를 사용할 수 없습니다.')
    try:
        api=api or _native_api()
        if not api.IsWindow(hwnd) or api.GetAncestor(hwnd,2)!=hwnd:
            return ExclusionStatus(False,'최상위 오버레이 창을 확인하지 못했습니다.')
        pid=wintypes.DWORD()
        api.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        if pid.value!=os.getpid():
            return ExclusionStatus(False,'다른 프로세스 창에는 적용하지 않습니다.')
        if hasattr(ctypes,'set_last_error'):ctypes.set_last_error(0)
        if not api.SetWindowDisplayAffinity(hwnd,WDA_EXCLUDEFROMCAPTURE):
            return ExclusionStatus(False,'Windows가 오버레이 영상 제외 설정을 거부했습니다.',getattr(ctypes,'get_last_error',lambda:0)())
        actual=wintypes.DWORD()
        if not api.GetWindowDisplayAffinity(hwnd,ctypes.byref(actual)) or actual.value!=WDA_EXCLUDEFROMCAPTURE:
            return ExclusionStatus(False,'영상 제외 속성의 적용을 확인하지 못했습니다.')
        return ExclusionStatus(True,'WDA_EXCLUDEFROMCAPTURE 설정 및 읽기 확인 완료')
    except Exception as exc:
        return ExclusionStatus(False,f'Windows 영상 제외 API 오류: {type(exc).__name__}')
