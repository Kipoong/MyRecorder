"""Qt logical coordinates to Win32 physical desktop coordinates."""
from dataclasses import dataclass
import math
import os


class DisplayError(RuntimeError):
    pass


@dataclass(frozen=True)
class NativeMonitor:
    name: str
    rect: tuple[int, int, int, int]


def map_region(region, logical_screen, physical_screen):
    x,y,w,h = region
    lx,ly,lw,lh = logical_screen
    px,py,pw,ph = physical_screen
    if any(not math.isfinite(v) for v in (*region,*logical_screen,*physical_screen)):
        raise DisplayError('유효하지 않은 화면 좌표입니다.')
    if min(w,h,lw,lh,pw,ph) <= 0 or x < lx or y < ly or x+w > lx+lw or y+h > ly+lh:
        raise DisplayError('녹화/OCR 영역은 한 모니터 안에 있어야 합니다. 영역을 다시 선택하세요.')
    left = px+round((x-lx)*pw/lw)
    top = py+round((y-ly)*ph/lh)
    right = px+round((x+w-lx)*pw/lw)
    bottom = py+round((y+h-ly)*ph/lh)
    if right <= left or bottom <= top:
        raise DisplayError('영역이 너무 작습니다.')
    return left,top,right-left,bottom-top


def native_monitors():
    if os.name != 'nt':
        raise DisplayError('Windows의 물리 모니터 좌표를 읽을 수 없습니다.')
    import ctypes
    from ctypes import wintypes
    class Info(ctypes.Structure):
        _fields_ = [('cbSize',wintypes.DWORD),('rcMonitor',wintypes.RECT),
                    ('rcWork',wintypes.RECT),('dwFlags',wintypes.DWORD),('szDevice',wintypes.WCHAR*32)]
    api=ctypes.WinDLL('user32',use_last_error=True)
    api.GetMonitorInfoW.argtypes=[wintypes.HANDLE,ctypes.POINTER(Info)]
    api.GetMonitorInfoW.restype=wintypes.BOOL
    callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HANDLE,wintypes.HDC,
                                   ctypes.POINTER(wintypes.RECT),wintypes.LPARAM)
    monitors=[];errors=[]
    def collect(handle,hdc,rect,param):
        info=Info();info.cbSize=ctypes.sizeof(Info)
        if not api.GetMonitorInfoW(handle,ctypes.byref(info)):
            errors.append(ctypes.get_last_error());return False
        r=info.rcMonitor
        monitors.append(NativeMonitor(info.szDevice,(r.left,r.top,r.right-r.left,r.bottom-r.top)))
        return True
    callback=callback_type(collect)
    api.EnumDisplayMonitors.argtypes=[wintypes.HDC,ctypes.POINTER(wintypes.RECT),callback_type,wintypes.LPARAM]
    api.EnumDisplayMonitors.restype=wintypes.BOOL
    if not api.EnumDisplayMonitors(None,None,callback,0) or errors:
        raise DisplayError('Win32 모니터 좌표 조회 실패. 모니터 연결과 DPI 설정을 확인하세요.')
    return monitors


def dpi_awareness():
    if os.name != 'nt': return None
    import ctypes
    api=ctypes.WinDLL('user32',use_last_error=True)
    try:
        api.GetThreadDpiAwarenessContext.argtypes=[]
        api.GetThreadDpiAwarenessContext.restype=ctypes.c_void_p
        api.GetAwarenessFromDpiAwarenessContext.argtypes=[ctypes.c_void_p]
        api.GetAwarenessFromDpiAwarenessContext.restype=ctypes.c_int
        return api.GetAwarenessFromDpiAwarenessContext(api.GetThreadDpiAwarenessContext())
    except AttributeError:
        return None


def physical_region(screen, region):
    logical=screen.geometry()
    name=screen.name().casefold()
    candidates=[m for m in native_monitors() if m.name.casefold()==name]
    if len(candidates)!=1:
        raise DisplayError('Qt 화면과 Windows 모니터를 정확히 대응시키지 못했습니다. 앱을 재시작하고 다시 선택하세요.')
    if abs(screen.devicePixelRatio()-1)>0.01 and dpi_awareness()!=2:
        raise DisplayError('현재 프로세스가 모니터별 DPI 모드가 아닙니다. Windows 호환성 DPI 재정의를 해제하고 재실행하세요. 임시 대안은 배율 100%입니다.')
    return map_region((region.x(),region.y(),region.width(),region.height()),
                      (logical.x(),logical.y(),logical.width(),logical.height()),candidates[0].rect)


def capture_png(screen, region):
    """Run on Qt GUI thread; cropped image stays in memory, never in OneDrive."""
    from PySide6.QtCore import QBuffer, QIODevice
    physical=physical_region(screen,region)
    full=physical_region(screen,screen.geometry())
    image=screen.grabWindow(0).toImage()
    if image.isNull() or abs(image.width()-full[2])>2 or abs(image.height()-full[3])>2:
        raise DisplayError('OCR 화면 캡처 크기가 모니터의 물리 크기와 다릅니다. 화면 배율과 선택 모니터를 확인하세요.')
    x,y,w,h=physical
    image=image.copy(x-full[0],y-full[1],w,h)
    buffer=QBuffer();buffer.open(QIODevice.WriteOnly)
    if not image.save(buffer,'PNG'):
        raise DisplayError('OCR 이미지를 만들지 못했습니다.')
    return bytes(buffer.data())
