"""Configure process DPI once, before QApplication; keep already fixed contexts."""
import os

QT_AWARENESS={'unaware':0,'system':1,'per_monitor':2,'per_monitor_v2':3}
_STATE=None


class WindowsDpiAPI:
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes=ctypes
        self.user=ctypes.WinDLL('user32',use_last_error=True)
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.kernel.GetCurrentProcess.argtypes=[];self.kernel.GetCurrentProcess.restype=wintypes.HANDLE
        self.user.GetDpiAwarenessContextForProcess.argtypes=[wintypes.HANDLE]
        self.user.GetDpiAwarenessContextForProcess.restype=ctypes.c_void_p
        self.user.GetThreadDpiAwarenessContext.argtypes=[];self.user.GetThreadDpiAwarenessContext.restype=ctypes.c_void_p
        self.user.AreDpiAwarenessContextsEqual.argtypes=[ctypes.c_void_p,ctypes.c_void_p]
        self.user.AreDpiAwarenessContextsEqual.restype=wintypes.BOOL
        self.user.SetProcessDpiAwarenessContext.argtypes=[ctypes.c_void_p]
        self.user.SetProcessDpiAwarenessContext.restype=wintypes.BOOL
    def _kind(self,context):
        for value,name in [(-4,'per_monitor_v2'),(-3,'per_monitor'),(-2,'system'),(-1,'unaware'),(-5,'gdi_scaled')]:
            if self.user.AreDpiAwarenessContextsEqual(context,self.ctypes.c_void_p(value)):return name
        return 'unknown'
    def snapshot(self):
        return {'process':self._kind(self.user.GetDpiAwarenessContextForProcess(self.kernel.GetCurrentProcess())),
                'thread':self._kind(self.user.GetThreadDpiAwarenessContext())}
    def enable_v2(self):
        self.ctypes.set_last_error(0)
        success=bool(self.user.SetProcessDpiAwarenessContext(self.ctypes.c_void_p(-4)))
        return success,self.ctypes.get_last_error()


def runtime_dpi():
    if os.name!='nt':return {'process':'non_windows','thread':'non_windows'}
    try:return WindowsDpiAPI().snapshot()
    except Exception as exc:return {'process':'unknown','thread':'unknown','error':type(exc).__name__}


def configure_dpi(api, environment):
    before=api.snapshot()
    state={'before':before,'after':before,'set_attempted':False,'set_succeeded':False,'error_code':0}
    if before['process']!=before['thread']:
        state['error']='DPI_PROCESS_THREAD_CONFLICT';return state
    if before['process']=='unaware':
        # An explicitly locked unaware process cannot be distinguished in advance.
        # Make at most one attempt, then retain the observed state without retries.
        state['set_attempted']=True
        state['set_succeeded'],state['error_code']=api.enable_v2()
        state['after']=api.snapshot()
    after=state['after']
    if after['process']!=after['thread'] or after['thread'] not in QT_AWARENESS:
        state['error']='DPI_CONTEXT_UNSUPPORTED';return state
    platform=environment.get('QT_QPA_PLATFORM','windows')
    if platform.split(':',1)[0].lower()!='windows' or ';' in platform:
        state['error']='QT_PLATFORM_OVERRIDE_UNSUPPORTED';return state
    options=[option for option in platform.split(':')[1:] if not option.lower().startswith('dpiawareness=')]
    options.append(f"dpiawareness={QT_AWARENESS[after['thread']]}")
    environment['QT_QPA_PLATFORM']='windows:'+':'.join(options)
    state['qt_platform']=environment['QT_QPA_PLATFORM']
    state['policy']='preserve_observed_context; Qt requests the same context'
    return state


def prepare_dpi():
    global _STATE
    if _STATE is not None:return _STATE
    if os.name!='nt':
        _STATE={'policy':'non_windows; no DPI setter or environment changes'}
    else:
        try:_STATE=configure_dpi(WindowsDpiAPI(),os.environ)
        except Exception as exc:_STATE={'error':'DPI_BOOTSTRAP_FAILED','detail':type(exc).__name__}
    return _STATE


def dpi_report():
    return {'bootstrap':_STATE,'runtime':runtime_dpi(),
            'qt_environment':{key:os.environ.get(key) for key in ('QT_QPA_PLATFORM','QT_SCALE_FACTOR',
                         'QT_SCREEN_SCALE_FACTORS','QT_ENABLE_HIGHDPI_SCALING')}}


def launch():
    state=prepare_dpi()
    if state.get('error'):
        message=f"DPI 초기화 실패: {state['error']}\n프로세스/스레드의 DPI 설정 또는 Windows 호환성 DPI 재정의를 확인하세요.\n검증되지 않은 좌표로 녹화하지 않도록 실행을 중단합니다."
        # This is before Qt/GUI creation. Do not invoke a second Qt DPI setter for the error dialog.
        try:
            from .coordinate_log import new_coordinate_log
            log=new_coordinate_log()
            log.write('dpi_bootstrap_failed',state=state)
            message+=f'\n진단 로그: {log.path}'
        except Exception:
            message+='\n설정의 Temp 폴더에 로그를 쓰지 못했습니다. 자동 대체 경로는 사용하지 않습니다.'
        print(message)
        if os.name=='nt':
            import ctypes
            api=ctypes.WinDLL('user32')
            api.MessageBoxW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_uint]
            api.MessageBoxW.restype=ctypes.c_int
            api.MessageBoxW(None,message,'MyRecorder DPI 초기화',0x10)
        raise SystemExit(2)
    from .gui import main
    main()
