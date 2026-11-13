"""Optional Linux offscreen settings smoke test; not a Windows recorder test.
QT_QPA_PLATFORM=offscreen python tests/gui_smoke.py
Run with project root on PYTHONPATH, e.g. PYTHONPATH=. on Linux.
"""
import sys
from pathlib import Path
import tempfile
from unittest.mock import patch, Mock
from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtCore import QEventLoop, QTimer, QRect
from PySide6.QtGui import QCloseEvent
from types import SimpleNamespace
from myrecorder.settings import SettingsStore, StoragePaths
from myrecorder.gui import Window, StorageDialog
from myrecorder.titles import LectureWindow, TitleError

qt_errors=[]
original_hook=sys.excepthook
sys.excepthook=lambda kind,value,trace: qt_errors.append(f'{kind.__name__}: {value}')
app = QApplication([])
def wait_for_job(window):
    loop=QEventLoop()
    timer=QTimer()
    timer.timeout.connect(lambda: loop.quit() if window.job is None and not window.capture_pending else None)
    timer.start(10)
    QTimer.singleShot(5000,loop.quit)
    loop.exec()
    timer.stop()
    assert window.job is None and not window.capture_pending, 'GUI worker did not finish'

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
    failed=SimpleNamespace(process=None,folder=root/'임시 영상'/'failed-session',elapsed=0.0,started=0.0,stop_requested_at=None)
    failed.folder.mkdir()
    def fail_start(): raise RuntimeError('[DEVICE_OPEN_FAILED] mock failure')
    failed.start=fail_start
    with patch('myrecorder.gui.physical_region',return_value=(0,0,320,180)), patch('myrecorder.gui.Recorder',return_value=failed) as factory, patch('myrecorder.gui.QMessageBox.critical') as error:
        window.start()
        wait_for_job(window)
        assert factory.call_args.args[0].system_device['index']==1
        assert error.called
        assert window.state=='idle' and window.recorder is None
        assert window.output_device.isEnabled() and failed.folder.exists()
    with patch('myrecorder.gui.list_windows',return_value=[LectureWindow(101,'Example Lecture',456)]):
        window.refresh_title_windows();wait_for_job(window)
    window.lecture_window.setCurrentIndex(1)
    with patch('myrecorder.gui.window_title',return_value='Example Lecture 42'):
        window.recognize_title();wait_for_job(window)
    assert window.title.text()=='Example Lecture 42' and window.title_source=='window'
    with patch('myrecorder.gui.window_title',side_effect=TitleError('example failure')),patch('myrecorder.gui.QMessageBox.warning'):
        window.recognize_title();wait_for_job(window)
    assert window.title.text()=='Example Lecture 42'
    window.ocr_region=QRect(10,10,120,50);window.ocr_screen=app.primaryScreen()
    window.title_mode.setCurrentIndex(1)
    with patch('myrecorder.gui.capture_png',return_value=b'PNG'),patch('myrecorder.gui.ocr_title',return_value='Example OCR Lecture') as recognize:
        window.recognize_title();wait_for_job(window)
        recognize.assert_called_once()
    assert window.title.text()=='Example OCR Lecture' and window.title_source=='ocr'
    window.title.textEdited.emit('Manual Title')
    assert window.title_source=='manual'
    window.state='recording';window.refresh()
    with patch('myrecorder.gui.ocr_title') as recognize:
        window.recognize_title()
        recognize.assert_not_called()
    assert not window.title_button.isEnabled() and not window.cleanup_button.isEnabled()
    window.state='idle';window.refresh()
    window.set_clock(3661.8);assert window.clock.text()=='01:01:01'
    preserved=root/'preserved-original.mkv';preserved.write_bytes(b'original')
    window.state='paused';window.recorder=SimpleNamespace(folder=root,events=SimpleNamespace(write=Mock()),process=None,elapsed=0.0,started=0.0,stop_requested_at=None)
    event=QCloseEvent()
    with patch('myrecorder.gui.QMessageBox.question',return_value=QDialog.Rejected):
        window.closeEvent(event)
        assert not event.isAccepted()
    from PySide6.QtWidgets import QMessageBox
    event=QCloseEvent()
    with patch('myrecorder.gui.QMessageBox.question',return_value=QMessageBox.Yes):
        window.closeEvent(event)
        assert event.isAccepted() and preserved.exists()
    window.state='idle';window.recorder=None
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
assert not qt_errors, qt_errors
sys.excepthook=original_hook
print('Qt offscreen storage/audio, title/OCR actions and failure fallback, recording locks, clock: PASS')
