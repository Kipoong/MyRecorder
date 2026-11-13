"""Qt auto-link lifecycle with a simulated recorder. Real Windows is not exercised."""
import sys,time,tempfile,traceback
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
from PySide6.QtCore import QRect,QEventLoop,QTimer
from PySide6.QtWidgets import QApplication
from myrecorder.gui import Window
from myrecorder.settings import SettingsStore,StoragePaths
from myrecorder.media import publish
errors=[]
def exception(kind,value,tb):errors.append(str(value));traceback.print_exception(kind,value,tb)
sys.excepthook=exception
app=QApplication([]);app.setQuitOnLastWindowClosed(False)
def until(predicate):
    loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if predicate() else None)
    timer.start(5);QTimer.singleShot(6000,loop.quit);loop.exec();timer.stop();assert predicate(),'GUI condition timed out'
engines=[]
class Engine:
    def __init__(self,opts):
        self.options=opts;self.process=None;self.audio=[];self.elapsed=0.;self.started=0.;self.stop_requested_at=None
        self.folder=opts.temp_folder/f'example-{len(engines)}';self.folder.mkdir(parents=True)
        self.events=SimpleNamespace(write=Mock());self.diagnostics=SimpleNamespace(path=self.folder/'example.jsonl')
        self.manifest={'warnings':[]};self.final_duration=None;self.segments=0;engines.append(self)
    def start(self):self.segments+=1;self.process=object();self.started=time.monotonic()
    def pause(self):self.process=None;self.elapsed+=1;self.stop_requested_at=time.monotonic()
    def finish(self):
        if self.process:self.pause()
        self.final_duration=self.elapsed
        temp=self.folder/'result.mp4';temp.write_bytes(b'simulated capture result, not real media')
        return publish(temp,self.options.folder,self.options.title)
    def health(self):return None
    def audio_status(self):return 'simulated audio'

with tempfile.TemporaryDirectory(prefix='auto-gui-example-') as d:
    root=Path(d);project=root/'project';project.mkdir();store=SettingsStore(project)
    store.save(StoragePaths(*(str(root/k) for k in ['Recordings','Converted','Temp'])))
    with patch('myrecorder.gui.physical_region',side_effect=lambda screen,r,**kwargs:(r.x(),r.y(),r.width(),r.height())),patch('myrecorder.gui.Recorder',side_effect=Engine):
        w=Window(store,check_startup=False);w.set_region(QRect(10,10,320,180));w.extension_id.setText('a'*32);w.open_browser_bridge()
        seq=[0];source={'key':'browser:tab:doc:video','title':'Example Lecture','origin':'https://example.invalid','state':'paused','supported':True,'video_label':'video 1','gate':'play-promise'}
        def send(kind,request=None):
            seq[0]+=1;return w.browser_bridge.ingest({'kind':kind,'source':source,'seq':seq[0],'event_wall_ms':time.time()*1000,'request_id':request})
        send('snapshot');w.browser_tick();w.auto_lead.setValue(0);w.auto_tail.setValue(0);w.auto_detect.setChecked(True)
        until(lambda:w.state=='paused' and not w.job)
        assert len(engines)==1 and engines[0].segments==1
        for i in range(5):
            send('prepare',f'play-{i}')
            until(lambda:w.state=='recording' and not w.job and w.browser_bridge.replies[f'play-{i}']['status']=='ready')
            send('playing');send('buffering');w.browser_tick();assert w.state=='recording'
            send('pause');until(lambda:w.state=='paused' and not w.job)
        assert len(engines)==1 and engines[0].segments==6
        send('prepare','manual-test');until(lambda:w.state=='recording' and not w.job)
        w.pause();until(lambda:w.state=='paused' and not w.job)
        send('prepare','blocked');w.browser_tick()
        assert w.browser_bridge.replies['blocked']['status']=='blocked' and w.state=='paused'
        w.pause();until(lambda:w.state=='recording' and not w.job)
        w.auto_link.end_stops=True;send('ended');until(lambda:w.state=='idle' and not w.job and not w.auto_link.enabled)
        assert len(list((root/'Recordings').glob('*.mp4')))==1
        assert w.title.isEnabled() and w.start_button.isEnabled() and w.border.phase=='idle'
        assert 'ready_ack' in w.auto_log.path.read_text()
        assert 'capture_started' in w.auto_log.path.read_text()
        assert w.browser_bridge.token not in w.auto_log.path.read_text()
        w.close();assert not w.browser_bridge.thread.is_alive()
assert not errors,errors
print('Qt auto warmup, 5 pause/resume cycles in one session, manual hold, ended save: PASS')
print('One simulated MP4, green idle restoration, delay logs without token, bridge cleanup: PASS')
