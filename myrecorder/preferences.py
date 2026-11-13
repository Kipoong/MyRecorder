"""Separate portable UI preferences; preserve existing storage settings unchanged."""
import json
import os
import tempfile
from pathlib import Path
from .modes import RecordingPolicy
from .settings import StorageError

class PreferencesStore:
    def __init__(self,root):self.root=Path(root);self.path=self.root/'preferences.json'
    def load(self):
        if not self.path.exists():return RecordingPolicy()
        try:
            data=json.loads(self.path.read_text(encoding='utf-8-sig'))
            if data.get('version')!=1:raise ValueError('지원하지 않는 환경 설정 버전')
            return RecordingPolicy(data['recording_mode'])
        except (OSError,ValueError,KeyError,TypeError,AttributeError) as exc:
            raise StorageError(f'녹화 유형 설정 오류: {self.path}\n{exc}\n기존 파일을 보존하고 preferences.example.json을 참고하세요.') from exc
    def save(self,policy):
        staging=None
        try:
            with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=self.root,prefix='.preferences-',suffix='.tmp',delete=False) as f:
                staging=Path(f.name)
                json.dump({'version':1,'recording_mode':policy.mode},f,ensure_ascii=False,indent=2)
                f.flush();os.fsync(f.fileno())
            os.replace(staging,self.path)
        except OSError as exc:raise StorageError(f'녹화 유형 저장 실패: {exc}') from exc
        finally:
            if staging:staging.unlink(missing_ok=True)
