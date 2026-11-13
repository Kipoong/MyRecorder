"""Native desktop modes, independent of DPI-virtualized monitor rectangles."""
from dataclasses import dataclass
import os


@dataclass(frozen=True)
class NativeMonitor:
    name: str
    rect: tuple[int,int,int,int]
    handle: int = 0
    reported_rect: tuple[int,int,int,int] | None = None
    primary: bool = False
    physical_source: str = 'synthetic'
    device_id: str = ''
    description: str = ''
    dpi: tuple[int,int] | None = None
    dpi_error: str | None = None


def query_monitors():
    if os.name!='nt':raise RuntimeError('NATIVE_WINDOWS_REQUIRED')
    import ctypes as c
    from ctypes import wintypes as w
    class Rect(c.Structure):_fields_=[('left',c.c_int32),('top',c.c_int32),('right',c.c_int32),('bottom',c.c_int32)]
    class Point(c.Structure):_fields_=[('x',c.c_int32),('y',c.c_int32)]
    class Info(c.Structure):
        _fields_=[('cbSize',c.c_uint32),('rcMonitor',Rect),('rcWork',Rect),('dwFlags',c.c_uint32),('szDevice',c.c_wchar*32)]
    class Mode(c.Structure):
        _fields_=[('dmDeviceName',c.c_wchar*32),('dmSpecVersion',c.c_uint16),('dmDriverVersion',c.c_uint16),
                  ('dmSize',c.c_uint16),('dmDriverExtra',c.c_uint16),('dmFields',c.c_uint32),
                  ('dmPosition',Point),('dmDisplayOrientation',c.c_uint32),('dmDisplayFixedOutput',c.c_uint32),
                  ('dmColor',c.c_int16),('dmDuplex',c.c_int16),('dmYResolution',c.c_int16),
                  ('dmTTOption',c.c_int16),('dmCollate',c.c_int16),('dmFormName',c.c_wchar*32),
                  ('dmLogPixels',c.c_uint16),('dmBitsPerPel',c.c_uint32),('dmPelsWidth',c.c_uint32),
                  ('dmPelsHeight',c.c_uint32),('dmDisplayFlags',c.c_uint32),('dmDisplayFrequency',c.c_uint32),
                  ('dmICMMethod',c.c_uint32),('dmICMIntent',c.c_uint32),('dmMediaType',c.c_uint32),
                  ('dmDitherType',c.c_uint32),('dmReserved1',c.c_uint32),('dmReserved2',c.c_uint32),
                  ('dmPanningWidth',c.c_uint32),('dmPanningHeight',c.c_uint32)]
    if c.sizeof(Info)!=104 or c.sizeof(Mode)!=220:raise RuntimeError('NATIVE_STRUCTURE_SIZE_INVALID')
    class Device(c.Structure):
        _fields_=[('cb',c.c_uint32),('DeviceName',c.c_wchar*32),('DeviceString',c.c_wchar*128),
                  ('StateFlags',c.c_uint32),('DeviceID',c.c_wchar*128),('DeviceKey',c.c_wchar*128)]
    api=c.WinDLL('user32',use_last_error=True)
    api.EnumDisplayDevicesW.argtypes=[w.LPCWSTR,w.DWORD,c.POINTER(Device),w.DWORD]
    api.EnumDisplayDevicesW.restype=w.BOOL
    shcore=c.WinDLL('shcore',use_last_error=True)
    shcore.GetDpiForMonitor.argtypes=[w.HANDLE,c.c_int,c.POINTER(c.c_uint32),c.POINTER(c.c_uint32)]
    shcore.GetDpiForMonitor.restype=c.c_int32
    api.GetMonitorInfoW.argtypes=[w.HANDLE,c.POINTER(Info)];api.GetMonitorInfoW.restype=w.BOOL
    api.EnumDisplaySettingsExW.argtypes=[w.LPCWSTR,w.DWORD,c.POINTER(Mode),w.DWORD]
    api.EnumDisplaySettingsExW.restype=w.BOOL
    callback_type=c.WINFUNCTYPE(w.BOOL,w.HANDLE,w.HDC,c.POINTER(Rect),w.LPARAM)
    monitors=[];errors=[]
    def collect(handle,hdc,rect,param):
        try:
            info=Info();info.cbSize=c.sizeof(Info)
            if not api.GetMonitorInfoW(handle,c.byref(info)):raise RuntimeError(f'GET_MONITOR_INFO_FAILED:{c.get_last_error()}')
            name=info.szDevice.strip()
            if not name:raise RuntimeError('NATIVE_DEVICE_NAME_EMPTY')
            mode=Mode();mode.dmSize=c.sizeof(Mode)
            if not api.EnumDisplaySettingsExW(name,0xffffffff,c.byref(mode),0):
                raise RuntimeError(f'PHYSICAL_DISPLAY_MODE_UNAVAILABLE:{c.get_last_error()}')
            required=0x20|0x80000|0x100000  # DM_POSITION | DM_PELSWIDTH | DM_PELSHEIGHT
            if mode.dmFields & required != required or min(mode.dmPelsWidth,mode.dmPelsHeight)==0:
                raise RuntimeError('PHYSICAL_DISPLAY_MODE_FIELDS_MISSING')
            r=info.rcMonitor
            device=Device();device.cb=c.sizeof(Device)
            found=api.EnumDisplayDevicesW(name,0,c.byref(device),1)
            dx=c.c_uint32();dy=c.c_uint32()
            dpi_result=shcore.GetDpiForMonitor(handle,0,c.byref(dx),c.byref(dy))
            monitors.append(NativeMonitor(name,(mode.dmPosition.x,mode.dmPosition.y,mode.dmPelsWidth,mode.dmPelsHeight),
                int(handle), (r.left,r.top,r.right-r.left,r.bottom-r.top),bool(info.dwFlags&1),'EnumDisplaySettingsExW',
                device.DeviceID if found else '',device.DeviceString if found else '',
                (dx.value,dy.value) if dpi_result==0 else None,
                f'GetDpiForMonitor HRESULT={dpi_result}' if dpi_result else None))
            return True
        except Exception as exc:
            errors.append(str(exc));return False
    callback=callback_type(collect)
    api.EnumDisplayMonitors.argtypes=[w.HDC,c.POINTER(Rect),callback_type,w.LPARAM];api.EnumDisplayMonitors.restype=w.BOOL
    if not api.EnumDisplayMonitors(None,None,callback,0) or errors or not monitors:
        raise RuntimeError('; '.join(errors) or 'ENUM_DISPLAY_MONITORS_FAILED')
    return monitors
