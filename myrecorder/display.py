"""Qt logical coordinates to Win32 physical desktop coordinates."""
import math
import os


from dataclasses import asdict
from .winmon import NativeMonitor, query_monitors
from .dpi_bootstrap import dpi_report


class DisplayError(RuntimeError):
    def __init__(self, message, code='DISPLAY_VALIDATION_FAILED', report=None):
        super().__init__(f'{message} [{code}]')
        self.code=code
        self.report=report or {}


def map_region(region, logical_screen, physical_screen):
    x,y,w,h = region
    lx,ly,lw,lh = logical_screen
    px,py,pw,ph = physical_screen
    if any(not math.isfinite(v) for v in (*region,*logical_screen,*physical_screen)):
        raise DisplayError('유효하지 않은 화면 좌표입니다.')
    if min(w,h,lw,lh,pw,ph) <= 0 or x < lx or y < ly or x+w > lx+lw or y+h > ly+lh:
        raise DisplayError('녹화/OCR 영역은 한 모니터 안에 있어야 합니다. 영역을 다시 선택하세요.','REGION_OUTSIDE_MONITOR')
    left = px+round((x-lx)*pw/lw)
    top = py+round((y-ly)*ph/lh)
    right = px+round((x+w-lx)*pw/lw)
    bottom = py+round((y+h-ly)*ph/lh)
    if right <= left or bottom <= top:
        raise DisplayError('영역이 너무 작습니다.')
    return left,top,right-left,bottom-top


def native_monitors():
    return query_monitors()


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


def rect_tuple(rect):
    return rect.x(),rect.y(),rect.width(),rect.height()


def normalize_name(name):
    name=name.rstrip('\0').strip().casefold()
    # Only standard Windows display prefixes are aliases; no substring guessing.
    for prefix in ('\\\\.\\', '\\\\?\\'):
        if name.startswith(prefix):name=name[len(prefix):]
    return name


def screen_snapshot(screen):
    return {'name':screen.name(),'rect':rect_tuple(screen.geometry()),
            'dpr':float(screen.devicePixelRatio()),'scale_percent':100*float(screen.devicePixelRatio()),
            'logical_dpi':float(screen.logicalDotsPerInch()) if hasattr(screen,'logicalDotsPerInch') else None,
            'primary':None}


def geometry_checks(qt, native):
    x,y,w,h=qt['rect'];px,py,pw,ph=native.rect;dpr=qt['dpr']
    return {'finite_positive':all(math.isfinite(v) for v in (x,y,w,h,px,py,pw,ph,dpr)) and min(w,h,pw,ph,dpr)>0,
            'origin':abs(x-px)<=1 and abs(y-py)<=1,
            'scaled_size':abs(w*dpr-pw)<=2 and abs(h*dpr-ph)<=2}


def match_monitor(selected, screens, monitors):
    """No list-index association. Unique identity AND geometry, or unique geometry."""
    if not monitors:raise DisplayError('Windows 모니터 목록이 비어 있습니다.','NATIVE_MONITORS_EMPTY')
    checks=[geometry_checks(selected,m) for m in monitors]
    named=[i for i,m in enumerate(monitors) if normalize_name(m.name)==normalize_name(selected['name'])]
    evidence={'normalized_name':normalize_name(selected['name']),'name_candidates':named,
              'geometry_checks':checks,'geometry_candidates':[i for i,c in enumerate(checks) if all(c.values())]}
    if len(named)>1:raise DisplayError('중복된 Windows 모니터 식별자입니다.','MONITOR_ID_AMBIGUOUS',evidence)
    if named:
        index=named[0]
        if not all(checks[index].values()):
            raise DisplayError('동일 식별자의 Qt 화면과 Windows 물리 영역이 다릅니다.','NAME_GEOMETRY_CONFLICT',evidence)
        strategy='identity_and_geometry'
    else:
        candidates=evidence['geometry_candidates']
        if len(candidates)!=1:
            raise DisplayError('좌표·배율로 모니터를 하나로 식별할 수 없습니다.','GEOMETRY_MATCH_NOT_UNIQUE',evidence)
        index=candidates[0]
        # A native monitor must not be compatible with two Qt screens.
        owners=[q for q in screens if all(geometry_checks(q,monitors[index]).values())]
        if len(owners)!=1:
            raise DisplayError('여러 Qt 화면이 동일한 Windows 영역에 대응합니다.','QT_GEOMETRY_AMBIGUOUS',evidence)
        strategy='unique_geometry'
    evidence.update(strategy=strategy,native_index=index,native_name=monitors[index].name)
    return monitors[index],evidence


def physical_region(screen, region, *, qt_screens=None, diagnostics=None, operation='mapping'):
    report={'operation':operation,'selected_region':rect_tuple(region),'dpi':dpi_report()}
    def emit(event):
        if diagnostics:diagnostics(event,**report)
    try:
        if qt_screens is None:
            from PySide6.QtGui import QGuiApplication
            app=QGuiApplication.instance()
            qt_screens=app.screens() if app else [screen]
        if screen not in qt_screens:
            raise DisplayError('선택한 모니터가 연결 해제되었거나 변경되었습니다.','SELECTED_SCREEN_REMOVED')
        snapshots=[screen_snapshot(q) for q in qt_screens]
        from PySide6.QtGui import QGuiApplication
        if QGuiApplication.instance():
            for q,snapshot in zip(qt_screens,snapshots):
                snapshot['primary']=q==QGuiApplication.primaryScreen()
        selected=screen_snapshot(screen)
        report.update(qt_screens=snapshots,selected_screen=selected)
        monitors=native_monitors()
        report['windows_monitors']=[{**asdict(m),'effective_scale_percent':100*m.dpi[0]/96 if m.dpi else None} for m in monitors]
        if monitors:
            left=min(m.rect[0] for m in monitors);top=min(m.rect[1] for m in monitors)
            right=max(m.rect[0]+m.rect[2] for m in monitors);bottom=max(m.rect[1]+m.rect[3] for m in monitors)
            report['physical_virtual_desktop']=(left,top,right-left,bottom-top)
        report['native_dpi_note']='GetDpiForMonitor is context-dependent; matching validates Qt DPR against physical mode size'
        monitor,evidence=match_monitor(selected,snapshots,monitors)
        report['matching']=evidence
        if abs(selected['dpr']-1)>0.01 and dpi_awareness()!=2:
            raise DisplayError('배율이 다른 화면에는 모니터별 DPI 인식이 필요합니다.','PER_MONITOR_DPI_REQUIRED')
        result=map_region(rect_tuple(region),selected['rect'],monitor.rect)
        report['physical_region']=result
        emit('display_mapping_ok')
        return result
    except Exception as exc:
        if isinstance(exc,DisplayError):
            report.update(failed_condition=exc.code,validation=exc.report,detail=str(exc))
        else:
            report.update(failed_condition='NATIVE_QUERY_FAILED',detail=f'{type(exc).__name__}: {exc}')
        emit('display_mapping_failed')
        raise DisplayError('화면 좌표를 안전하게 검증하지 못했습니다. '+report['detail'],
                           report['failed_condition'],report) from exc


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
