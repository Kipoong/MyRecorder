"""Synthetic Qt modes and physical desktop projection. No native Windows claims."""
import sys
import traceback
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
from PySide6.QtCore import QRect,QPoint,QPointF,Qt,QEventLoop,QTimer
from PySide6.QtWidgets import QApplication
from myrecorder.gui import Window
from myrecorder.settings import SettingsStore,StoragePaths
from myrecorder.display import NativeMonitor
from myrecorder.desktop_ui import DesktopDialog
from myrecorder.window_capture import ExclusionStatus
from myrecorder.media import publish

errors=[]
def exception(kind,value,tb):errors.append(str(value));traceback.print_exception(kind,value,tb)
sys.excepthook=exception
app=QApplication([]);app.setQuitOnLastWindowClosed(False)
def wait(w):
    loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if w.job is None else None)
    timer.start(5);QTimer.singleShot(10000,loop.quit);loop.exec();timer.stop()
    assert w.job is None

def screen(name,x,dpr=1):return SimpleNamespace(name=lambda:name,geometry=lambda:QRect(x,0,round(1920/dpr),round(1080/dpr)),devicePixelRatio=lambda:dpr)
screens=[screen('Example Left',-1920),screen('Example Right',0)]
monitors=[NativeMonitor('Example Right',(0,0,1920,1080)),NativeMonitor('Example Left',(-1920,0,1920,1080))]
mouse=lambda p:SimpleNamespace(globalPosition=lambda:QPointF(p),button=lambda:Qt.LeftButton,accept=lambda:None)
engines=[]
class Engine:
    def __init__(self,opts):
        self.options=opts;self.process=None;self.audio=[];self.elapsed=0.;self.started=0.;self.stop_requested_at=None
        self.folder=opts.temp_folder/f'example-{len(engines)}';self.folder.mkdir(parents=True)
        self.events=SimpleNamespace(write=Mock());self.diagnostics=SimpleNamespace(path=self.folder/'example.jsonl')
        self.manifest={'warnings':[]};self.final_duration=None;self.segments=0;engines.append(self)
    def start(self):self.segments+=1;self.process=object();self.started=time.monotonic()
    def pause(self):self.process=None;self.elapsed+=1
    def finish(self):
        self.pause();self.final_duration=self.elapsed
        tmp=self.folder/'example.mp4';tmp.write_bytes(b'synthetic fixture, not valid MP4')
        return publish(tmp,self.options.folder,self.options.title)
    def health(self):return None
    def audio_status(self):return 'synthetic silence; capture remains active'

with tempfile.TemporaryDirectory(prefix='modes-desktop-example-') as d:
    root=Path(d);project=root/'project';project.mkdir();store=SettingsStore(project)
    store.save(StoragePaths(*(str(root/k) for k in ('Recordings','Converted','Temp'))))
    with patch('myrecorder.gui.QApplication.screens',return_value=screens),patch('myrecorder.display.native_monitors',return_value=monitors),patch('myrecorder.desktop.native_monitors',return_value=monitors),patch('myrecorder.gui.Recorder',side_effect=Engine):
        w=Window(store,check_startup=False);w.full_desktop()
        assert w.desktop_mode and w.region==QRect(-1920,0,3840,1080) and w.start_button.isEnabled()
        entries=w.desktop_entries
        dialog=DesktopDialog(entries,w.desktop_bounds,(-200,100,811,513),w)
        assert dialog.selected==(-200,100,811,513)
        dialog.set_fields((-200,100,811,513));dialog.accept()
        w.set_desktop_region(dialog.selected,entries,w.desktop_bounds,w.desktop_signature)
        assert len(w.desktop_border.children_frames)==2
        left=w.desktop_border.children_frames['Example Left']
        right=w.desktop_border.children_frames['Example Right']
        assert left.selected==QRect(-200,100,200,513)
        assert right.selected==QRect(0,100,611,513)
        for child in w.desktop_border.children_frames.values():child._protect=lambda hwnd:ExclusionStatus(True,'synthetic only')
        w.refresh()
        # Resize a real outer handle; the internal monitor seam has no side resize grip.
        assert 'w' in left._handles and 'e' not in left._handles
        point=left._handles['w'].center();left.mousePressEvent(mouse(point));left.mouseMoveEvent(mouse(point-QPoint(50,0)));left.mouseReleaseEvent(mouse(point-QPoint(50,0)))
        assert w.region==QRect(-250,100,861,513)
        selected=QRect(w.region)
        w.title.setText('Example Lecture');w.start();wait(w)
        engine=engines[-1];assert engine.options.recording_mode=='lecture'
        assert engine.options.rect==(-250,100,861,513)
        for i in range(5):
            w.pause();wait(w);assert w.state=='paused' and w.desktop_border.phase=='paused'
            saved_elapsed=engine.elapsed;engine.started-=30;w.tick();assert engine.elapsed==saved_elapsed
            # Programmatic mode changes are also rejected while paused.
            w.recording_type.setCurrentIndex(1);assert w.policy.mode=='lecture'
            w.pause();wait(w);assert w.state=='recording' and w.desktop_border.phase=='recording'
        assert engine.segments==6
        w.stop();wait(w)
        assert w.state=='idle' and w.desktop_border.phase=='idle' and w.start_button.isEnabled() and w.region==selected
        assert len(list((root/'Recordings').glob('*.mp4')))==1
        w.recording_type.setCurrentIndex(1);assert w.policy.mode=='general'
        w.start();wait(w);engine=engines[-1]
        assert engine.options.recording_mode=='general' and not w.recording_type.isEnabled()
        for event in ['source_paused','unchanged_frame','silent']:
            assert w.policy.playback_action(event)=='continue'
        engine.started-=4;w.tick()
        assert w.state=='recording' and w.clock.text()>='00:00:04'
        assert engine.process is not None
        # Any unprotected child means hide all desktop overlays during capture.
        left._protect=lambda hwnd:ExclusionStatus(False,'synthetic denied');w.sync_overlay()
        assert not w.desktop_border.isVisible()
        w.pause();wait(w);assert w.pause_button.text()=='재개'
        w.stop();wait(w);assert w.state=='idle' and w.title.isEnabled()
        for dpr in [1.25,1.5]:
            screens[0]=screen('Example Left',-1920,dpr)
            with patch('myrecorder.desktop.dpi_awareness',return_value=2):
                w.full_desktop()
                w.set_desktop_region((-200,100,811,513),w.desktop_entries,w.desktop_bounds,w.desktop_signature)
                child=w.desktop_border.children_frames['Example Left']
                assert abs(child.selected.width()-round(200/dpr))<=1
                assert w.map_selected('mixed_dpi_test')==(-200,100,811,513)
        # A changed native layout cannot silently reuse an old physical selection.
        changed=[NativeMonitor('Example Right',(10,0,1920,1080)),monitors[1]]
        with patch('myrecorder.desktop.native_monitors',return_value=changed),patch('myrecorder.desktop.dpi_awareness',return_value=2):
            w.refresh();assert not w.start_button.isEnabled()
        screens[0]=screen('Example Left',-1920)
        w.close()
        w=Window(store,check_startup=False);assert w.policy.mode=='general'
        w.close()
assert not errors,errors
print('Qt lecture 5 pauses/resumes, general still/silent timer, mode lock/persistence: PASS')
print('Qt physical desktop picker, two-monitor projections, seam/resize and exclusion fallback: PASS')
print('Capture/audio and native monitor APIs were simulated; actual Windows remains unverified.')
