"""Optional Linux offscreen settings smoke test; not a Windows recorder test.
QT_QPA_PLATFORM=offscreen python tests/gui_smoke.py
Run with project root on PYTHONPATH, e.g. PYTHONPATH=. on Linux.
"""
from pathlib import Path
import tempfile
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtCore import QEventLoop, QTimer
from types import SimpleNamespace
from myrecorder.settings import SettingsStore, StoragePaths
from myrecorder.gui import Window, StorageDialog

app = QApplication([])
def wait_for_job(window):
    loop=QEventLoop()
    timer=QTimer()
    timer.timeout.connect(lambda: loop.quit() if window.job is None else None)
    timer.start(10)
    QTimer.singleShot(5000,loop.quit)
    loop.exec()
    timer.stop()
    assert window.job is None, 'GUI worker did not finish'

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
    choices=[{'index':1,'name':'Example Speakers', 'channels':2,'rate':48000,
              'loopback_index':3,'available':True,'default':True},
             {'index':2,'name':'Example HDMI Output', 'channels':2,'rate':48000,
              'loopback_index':4,'available':True,'default':False}]
    with patch('myrecorder.gui.device_choices',return_value=choices):
        window.refresh_audio_devices()
        wait_for_job(window)
    assert window.output_device.count()==3
    window.output_device.setCurrentIndex(1)
    assert window.output_device.currentData()['index']==1
    assert 'Example Speakers' in window.audio_hint.text()
    failed=SimpleNamespace(process=None,folder=root/'임시 영상'/'failed-session')
    failed.folder.mkdir()
    def fail_start(): raise RuntimeError('[DEVICE_OPEN_FAILED] mock failure')
    failed.start=fail_start
    with patch('myrecorder.gui.Recorder',return_value=failed) as factory, patch('myrecorder.gui.QMessageBox.critical') as error:
        window.start()
        wait_for_job(window)
        assert factory.call_args.args[0].system_device['index']==1
        assert error.called
        assert window.state=='idle' and window.recorder is None
        assert window.output_device.isEnabled() and failed.folder.exists()
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
print('Qt offscreen storage, device selection, failed-start retry and recording-block: PASS')
