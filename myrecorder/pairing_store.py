"""Current-Windows-user DPAPI storage. Never save plaintext credentials."""
import ctypes
import json
import os
from pathlib import Path
import re
import tempfile

class PairingError(RuntimeError):pass

class DPAPI:
    def __init__(self):
        if os.name!='nt':raise PairingError('저장한 연결 복원은 Windows DPAPI가 필요합니다.')
        from ctypes import wintypes as w
        class Blob(ctypes.Structure):_fields_=[('size',w.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
        self.Blob=Blob;self.api=ctypes.WinDLL('crypt32',use_last_error=True)
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.api.CryptProtectData.argtypes=[ctypes.POINTER(Blob),w.LPCWSTR,ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,w.DWORD,ctypes.POINTER(Blob)]
        self.api.CryptUnprotectData.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,w.DWORD,ctypes.POINTER(Blob)]
        self.api.CryptProtectData.restype=w.BOOL;self.api.CryptUnprotectData.restype=w.BOOL
        self.kernel.LocalFree.argtypes=[ctypes.c_void_p];self.kernel.LocalFree.restype=ctypes.c_void_p
    def transform(self,data,encrypt):
        buffer=(ctypes.c_ubyte*len(data)).from_buffer_copy(data)
        source=self.Blob(len(data),buffer);result=self.Blob()
        args=[ctypes.byref(source),'MyRecorder pairing' if encrypt else None,None,None,None,1,ctypes.byref(result)]
        function=self.api.CryptProtectData if encrypt else self.api.CryptUnprotectData
        if not function(*args):raise PairingError(f'Windows 인증 정보 암호화/복호화 실패 (오류 {ctypes.get_last_error()})')
        try:return ctypes.string_at(result.data,result.size)
        finally:self.kernel.LocalFree(ctypes.cast(result.data,ctypes.c_void_p))
    def protect(self,data):return self.transform(data,True)
    def unprotect(self,data):return self.transform(data,False)

def validate(data):
    if not isinstance(data,dict) or data.get('version')!=1:raise PairingError('지원하지 않는 연결 정보입니다.')
    if not re.fullmatch('[a-p]{32}',str(data.get('extension_id',''))):raise PairingError('잘못된 확장 ID입니다.')
    if not re.fullmatch('[a-f0-9]{64}',str(data.get('token',''))):raise PairingError('잘못된 인증 정보입니다.')
    if type(data.get('port')) is not int or not 1<=data['port']<=65535:raise PairingError('잘못된 연결 포트입니다.')
    return data

class PairingStore:
    def __init__(self,path=None,crypto=None):
        if path is None:
            home=os.environ.get('LOCALAPPDATA')
            if not home or not Path(home).is_absolute():raise PairingError('LOCALAPPDATA 경로를 확인할 수 없습니다.')
            path=Path(home)/'MyRecorder'/'browser-pairing.dpapi'
        self.path=Path(path);self.crypto=crypto or DPAPI()
    def load(self):
        if not self.path.exists():return None
        try:
            if self.path.stat().st_size>65536:raise ValueError('oversized')
            return validate(json.loads(self.crypto.unprotect(self.path.read_bytes()).decode('utf-8')))
        except Exception as exc:
            raise PairingError('저장한 연결을 복원하지 못했습니다. 파일을 보존했으며 연결 초기화 후 다시 페어링할 수 있습니다.') from exc
    def save(self,extension_id,pairing):
        data=validate({'version':1,'extension_id':extension_id,**pairing});temporary=None
        try:
            encrypted=self.crypto.protect(json.dumps(data).encode('utf-8'))
            self.path.parent.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile('wb',dir=self.path.parent,prefix='.pairing-',delete=False) as f:
                temporary=Path(f.name);f.write(encrypted);f.flush();os.fsync(f.fileno())
            os.replace(temporary,self.path)
        except Exception as exc:raise PairingError('연결 정보를 안전하게 저장하지 못했습니다. 평문 대체 저장은 하지 않습니다.') from exc
        finally:
            if temporary:temporary.unlink(missing_ok=True)
    def reset(self):self.path.unlink(missing_ok=True)
