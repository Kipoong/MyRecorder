"""Local-only coordinate diagnostics; never fall back to the project folder."""
from pathlib import Path
import uuid
from .audio import Diagnostics
from .settings import SettingsStore, storage_directory


def new_coordinate_log(paths=None, development=None):
    if paths is None:
        store=SettingsStore()
        paths=store.load();development=store.root
    folder=storage_directory(paths.temp,development)
    return Diagnostics(Path(folder)/('display-diagnostics-'+uuid.uuid4().hex+'.jsonl'))
