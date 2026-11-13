"""Qt state/dual-screen simulation with real publish; no native Windows capture."""
import sys
import traceback
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock
from PySide6.QtCore import QRect, QPoint, QPointF, Qt, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from myrecorder.gui import Window
from myrecorder.settings import SettingsStore, StoragePaths
from myrecorder.display import NativeMonitor, DisplayError
from myrecorder.media import publish
from myrecorder.window_capture import ExclusionStatus
from myrecorder.overlay import COLORS

errors=[]
def exception(kind,value,tb):
    errors.append(f'{kind.__name__}: {value}')
    traceback.print_exception(kind,value,tb)
sys.excepthook=exception
app=QApplication([]);app.setQuitOnLastWindowClosed(False)
def wait(window):
    loop=QEventLoop();timer=QTimer()
    timer.timeout.connect(lambda:loop.quit() if window.job is None else None)
    timer.start(10);QTimer.singleShot(10000,loop.quit);loop.exec();timer.stop()
    assert window.job is None,'job did not finish'
def screen(name,x):return SimpleNamespace(name=lambda:name,geometry=lambda:QRect(x,0,1920,1080),devicePixelRatio=lambda:1.)
screens=[screen('Example Left',-1920),screen('Example Right',0)]
monitors=[NativeMonitor('Example Right',(0,0,1920,1080)),NativeMonitor('Example Left',(-1920,0,1920,1080))]
mouse=lambda p:SimpleNamespace(globalPosition=lambda:QPointF(p),button=lambda:Qt.LeftButton,accept=lambda:None)

class Engine:
    def __init__(self,opts):
        self.options=opts;self.process=None;self.audio=[];self.elapsed=0.;self.started=0.;self.stop_requested_at=None
        self.folder=opts.temp_folder/f'session-example-{len(engines)}';self.folder.mkdir(parents=True)
        self.raw=self.folder/'original.mkv';self.raw.write_bytes(b'preserved original')
        self.events=SimpleNamespace(write=Mock());self.diagnostics=SimpleNamespace(path=self.folder/'diagnostics.jsonl')
        self.manifest={'warnings':[]};self.final_duration=None
        self.released=threading.Event();self.entered=threading.Event();self.fail=False
        engines.append(self)
    def start(self):assert self.process is None;self.process=object();self.started=time.monotonic()
    def pause(self):self.process=None;self.elapsed+=1
    def health(self):return None
    def audio_status(self):return 'synthetic system audio'
    def finish(self):
        self.entered.set()
        if not self.released.wait(5):raise RuntimeError('synthetic test timeout')
        self.pause()
        if self.fail:raise OSError('synthetic disk failure')
        self.final_duration=self.elapsed
        temp=self.folder/'candidate.mp4';temp.write_bytes(f'example session {len(engines)}'.encode())
        return publish(temp,self.options.folder,self.options.title)

engines=[]
with tempfile.TemporaryDirectory(prefix='continuous-example-') as d:
    root=Path(d);project=root/'project';project.mkdir();store=SettingsStore(project)
    store.save(StoragePaths(*(str(root/key) for key in ('Recordings','Converted','Temp'))))
    with patch('myrecorder.gui.QApplication.screens',return_value=screens),patch('myrecorder.display.native_monitors',return_value=monitors),patch('myrecorder.gui.QApplication.screenAt',side_effect=lambda point:screens[0] if point.x()<0 else screens[1]),patch('myrecorder.gui.Recorder',side_effect=Engine) as factory:
        w=Window(store,check_startup=False)
        w.border._protect=lambda hwnd:ExclusionStatus(True,'synthetic only')
        w.title.setText('Example Lecture')
        outputs=[];prior={}
        for i in range(3):
            target=screens[i%2];w.screen.setCurrentIndex(i%2)
            if i==0:w.set_region(QRect(-1800,100,400,250),target)
            else:
                # Transfer the existing frame across screen boundaries using real signal routing.
                old=QRect(w.region);anchor=w.border._label.center()
                destination=QPoint(300 if target is screens[1] else -1500,150)
                w.border.mousePressEvent(mouse(anchor));w.border.mouseMoveEvent(mouse(destination));w.border.mouseReleaseEvent(mouse(destination))
                assert w.region_screen is target
            fixed=QRect(w.region)
            assert w.start_button.isEnabled() and w.title.isEnabled() and w.border.editable
            w.start();wait(w)
            assert w.state=='recording' and w.border.phase=='recording' and not w.border.editable
            assert not w.title.isEnabled() and not w.start_button.isEnabled()
            assert factory.call_args.args[0].system is True
            assert factory.call_args.args[0].rect==(fixed.x(),fixed.y(),fixed.width(),fixed.height())
            w.overlay_region_changed(QRect(0,0,32,32));assert w.region==fixed
            if i==1:
                w.pause();wait(w)
                assert w.state=='paused' and w.border.phase=='paused' and w.pause_button.text()=='재개'
                assert not w.border.editable and w.stop_button.isEnabled()
                w.pause();wait(w);assert w.border.phase=='recording'
            engine=engines[-1]
            if i==2:engine.manifest['warnings']=['synthetic saved warning']
            w.stop()
            assert engine.entered.wait(2)
            assert w.state=='saving' and w.border.phase=='saving' and COLORS['saving']==COLORS['paused']
            assert not w.start_button.isEnabled() and not w.stop_button.isEnabled() and not w.title.isEnabled()
            before=len(engines);w.start();w.stop();assert len(engines)==before
            def saved_warning(*args):
                assert w.state=='idle' and w.recorder is None
                assert w.start_button.isEnabled() and w.title.isEnabled() and w.border.editable
            engine.released.set()
            with patch('myrecorder.gui.QMessageBox.warning',side_effect=saved_warning):wait(w)
            assert w.state=='idle' and w.recorder is None and w.border.phase=='idle'
            assert w.region==fixed and w.border.editable and w.title.isEnabled() and w.start_button.isEnabled()
            assert engine.process is None and engine.audio==[]
            assert w.last not in outputs;outputs.append(w.last)
            for path,data in prior.items():assert path.read_bytes()==data
            prior[w.last]=w.last.read_bytes()
        # Same region, same title, no re-selection: start again, fail save, retry.
        fixed=QRect(w.region);w.start();wait(w);failed=engines[-1];failed.fail=True
        w.stop();failed.released.set()
        with patch('myrecorder.gui.QMessageBox.critical') as warning:wait(w);assert warning.called
        assert w.state=='save_failed' and not w.start_button.isEnabled() and not w.pause_button.isEnabled()
        assert w.stop_button.isEnabled() and w.stop_button.text()=='저장 재시도' and failed.raw.exists()
        failed.fail=False;w.stop();wait(w)
        assert w.state=='idle' and w.region==fixed and w.start_button.isEnabled()
        # Invalid mapping and missing engine disable start without creating a session.
        with patch('myrecorder.gui.physical_region',side_effect=DisplayError('synthetic invalid')):
            w.refresh();assert not w.start_button.isEnabled()
        w.engine_error='synthetic ffmpeg missing';w.refresh();assert not w.start_button.isEnabled()
        w.engine_error=None;w.refresh();assert w.start_button.isEnabled()
        w.close()
assert not errors,errors
print('Qt 3 alternating-screen recordings + same-region restart + failed-save retry: PASS')
print('Saving locks, title/region restoration, collision-safe publish, readiness gates: PASS')
print('Capture, native drag and WASAPI were simulated; Windows validation is still required.')
