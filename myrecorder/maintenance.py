"""Explicit cleanup of verified saved sessions only. Failed sessions are preserved."""
from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil
from .media import probe


@dataclass(frozen=True)
class SavedSession:
    folder: Path
    output: Path
    bytes: int


def _link(path):
    return path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction())


def inspect_saved_session(temp_root: Path, folder: Path):
    root=Path(temp_root).resolve()
    folder=Path(folder)
    if not re.fullmatch(r'session-[0-9a-f]{32}',folder.name) or _link(folder): return None
    if folder.resolve().parent!=root or not folder.is_dir(): return None
    try:
        children=[]
        pending=[folder]
        while pending:
            for child in pending.pop().iterdir():
                if _link(child): return None
                children.append(child)
                if child.is_dir(): pending.append(child)
        data=json.loads((folder/'session.json').read_text(encoding='utf-8'))
        if not isinstance(data,dict): return None
        if data.get('owner')!='MyRecorder' or data.get('status')!='saved': return None
        segments=data.get('segments')
        if not isinstance(segments,list) or not segments or any(not isinstance(s,dict) or not s.get('complete') or s.get('startup_error') for s in segments): return None
        output=Path(data['output']['path'])
        if not output.is_absolute() or _link(output): return None
        if folder.resolve() in output.resolve().parents: return None
        if output.resolve().parent!=Path(data['recordings_folder']).resolve(): return None
        if not output.is_file() or output.stat().st_size!=data['output']['size'] or output.stat().st_size<=0: return None
        probe(output)  # refuse cleanup if the final MP4 cannot be read
        return SavedSession(folder.resolve(),output.resolve(),sum(p.stat().st_size for p in children if p.is_file()))
    except (OSError,ValueError,TypeError,KeyError,RuntimeError):
        return None


def saved_sessions(temp_root: Path):
    root=Path(temp_root)
    return [candidate for folder in root.glob('session-*')
            if (candidate:=inspect_saved_session(root,folder)) is not None]


def cleanup_sessions(temp_root: Path, folders):
    removed=[]
    for folder in folders:
        candidate=inspect_saved_session(temp_root,Path(folder))  # revalidate after confirmation
        if candidate is None:
            raise RuntimeError(f'완료 MP4를 검증할 수 없어 임시 파일을 보존했습니다: {folder}')
        shutil.rmtree(candidate.folder)
        removed.append(candidate.folder)
    return removed
