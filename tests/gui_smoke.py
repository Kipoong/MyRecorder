"""Optional Linux offscreen settings smoke test; not a Windows recorder test.
QT_QPA_PLATFORM=offscreen python tests/gui_smoke.py
Run with project root on PYTHONPATH, e.g. PYTHONPATH=. on Linux.
"""
from pathlib import Path
import tempfile
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QDialog
from myrecorder.settings import SettingsStore, StoragePaths
from myrecorder.gui import Window, StorageDialog

app = QApplication([])
with tempfile.TemporaryDirectory(prefix='GUI 한글 공백 ') as directory:
    root=Path(directory)
    development=root/'개발 경로'
    development.mkdir()
    store=SettingsStore(development)
    paths=StoragePaths(*(str(root/name) for name in ['녹화 저장','변환 영상','임시 영상']))
    store.save(paths)
    window=Window(store)
    app.processEvents()
    assert all(Path(p).is_dir() for p in (paths.recordings,paths.converted,paths.temp))
    assert window.folder.text()==paths.recordings and window.folder.isReadOnly()
    dialog=StorageDialog(store,paths,window)
    new_path=str(root/'새 녹화 경로')
    dialog.fields['recordings'].setText(new_path)
    dialog.save()
    assert dialog.result()==QDialog.Accepted
    assert SettingsStore(development).load().recordings==new_path
    window.close()
    store.save(StoragePaths('relative','relative2','relative3'))
    window=Window(store,check_startup=False)
    with patch('myrecorder.gui.QMessageBox.warning') as warning, patch.object(window,'choose_folder') as choose:
        window.start()
        assert warning.called and choose.called
        assert window.recorder is None and window.job is None
    window.close()
print('Qt offscreen settings and recording-block smoke test: PASS')
