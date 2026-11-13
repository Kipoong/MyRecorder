"""Qt synthetic overlay tests. Does NOT validate native Windows exclusion or hit testing."""
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock
from PySide6.QtCore import Qt, QRect, QPoint, QPointF, QEventLoop, QTimer, QEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor
from myrecorder.gui import Window
from myrecorder.settings import SettingsStore, StoragePaths
from myrecorder.window_capture import ExclusionStatus
from myrecorder.overlay import COLORS

errors=[]
sys.excepthook=lambda kind,value,trace:errors.append(f'{kind.__name__}: {value}')
app=QApplication([]);app.setQuitOnLastWindowClosed(False)

def wait(window):
    loop=QEventLoop();timer=QTimer()
    timer.timeout.connect(lambda:loop.quit() if window.job is None else None)
    timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop()
    assert window.job is None


def assert_color(border,phase):
    app.processEvents()
    image=border.grab().toImage()
    point=border._bands[0].center()-border.geometry().topLeft()
    x=round(point.x()*image.width()/border.width())
    y=round(point.y()*image.height()/border.height())
    assert image.pixelColor(x,y)==QColor(COLORS[phase])


def mouse(point):
    return SimpleNamespace(globalPosition=lambda:QPointF(point),button=lambda:Qt.LeftButton,accept=lambda:None)


with tempfile.TemporaryDirectory(prefix='overlay-example-') as d:
    root=Path(d);development=root/'project';development.mkdir()
    store=SettingsStore(development)
    paths=StoragePaths(*(str(root/key) for key in ('Recordings','Converted','Temp')))
    store.save(paths)
    with patch('myrecorder.gui.physical_region',side_effect=lambda screen,r:(r.x(),r.y(),r.width(),r.height())):
        window=Window(store,check_startup=False)
        window.border._protect=lambda hwnd:ExclusionStatus(True,'synthetic affinity result; not Windows')
        window.set_region(QRect(100,150,200,150))
        app.processEvents()
        assert window.border.isVisible() and window.border.phase=='idle'
        assert_color(window.border,'idle')
        assert window.border.physical[2:]==(200,150)
        assert '200×150 px' in window.region_label.text()
        # The native mask is not supported by offscreen. Verify its computed shape only.
        center=window.region.center()-window.border.geometry().topLeft()
        assert not window.border.mask().contains(center)
        label_center=window.border._label.center()
        window.border.mousePressEvent(mouse(label_center))
        window.border.mouseMoveEvent(mouse(label_center+QPoint(20,15)))
        window.border.mouseReleaseEvent(mouse(label_center+QPoint(20,15)))
        assert window.region==QRect(120,165,200,150)
        corner=window.region.bottomRight()
        window.border.mousePressEvent(mouse(corner))
        window.border.mouseMoveEvent(mouse(corner+QPoint(40,25)))
        window.border.mouseReleaseEvent(mouse(corner+QPoint(40,25)))
        assert window.region==QRect(120,165,240,175)
        assert window.border.physical[2:]==(240,175)
        window.border.mousePressEvent(mouse(window.border._label.center()))
        assert window.border._drag is not None
        window.border_toggle.setChecked(False);assert not window.border.isVisible() and window.border._drag is None
        window.border_toggle.setChecked(True);assert window.border.isVisible()
        fake=SimpleNamespace(process=None,elapsed=0.0,started=0.0,stop_requested_at=None,
            folder=root/'Temp'/'fake-session',events=SimpleNamespace(write=Mock()),manifest={'warnings':[]},
            diagnostics=SimpleNamespace(path=root/'Temp'/'fake-diagnostics.jsonl'),final_duration=None,
            health=lambda:None,audio_status=lambda:'synthetic audio state')
        def start():fake.started=time.monotonic();fake.process=object()
        def pause():fake.process=None;fake.elapsed+=2.0
        def finish():pause();fake.final_duration=4.0;return root/'Recordings'/'synthetic.mp4'
        fake.start,fake.pause,fake.finish=start,pause,finish
        with patch('myrecorder.gui.Recorder',return_value=fake) as factory:
            window.start();wait(window)
            assert window.state=='recording' and window.border.phase=='recording'
            assert_color(window.border,'recording')
            assert not window.border.editable
            assert window.border.windowFlags() & Qt.WindowTransparentForInput
            fixed=QRect(window.region)
            assert factory.call_args.args[0].rect==(120,165,240,175)
            window.overlay_region_changed(QRect(0,0,32,32));assert window.region==fixed
            window.set_region(QRect(0,0,32,32));assert window.region==fixed
            window.border_toggle.setChecked(False);assert not window.border.isVisible()
            window.border_toggle.setChecked(True);assert window.border.isVisible()
            # Native failure: continue the same capture without showing the overlay.
            window.border._protect=lambda hwnd:ExclusionStatus(False,'synthetic denied')
            window.border.event(QEvent(QEvent.WinIdChange))
            assert not window.border.isVisible() and fake.process is not None
            window.update_overlay_feedback()
            assert '자동 숨김' in window.border_hint.text()
            assert fake.events.write.call_args.kwargs['exclusion_applied'] is False
            window.sync_overlay();assert not window.border.isVisible() and fake.process is not None
            window.pause();wait(window)
            assert window.state=='paused' and window.border.phase=='paused'
            assert window.border.isVisible() and not window.border.editable
            assert_color(window.border,'paused')
            window.overlay_region_changed(QRect(0,0,32,32));assert window.region==fixed
            window.pause();wait(window)
            assert window.state=='recording' and not window.border.isVisible()
            # Saving can begin while the process is still alive; failure must hide here too.
            window.state='saving';window.sync_overlay()
            assert window.border.capture_active and not window.border.isVisible()
            window.state='recording'
            window.stop();wait(window)
            assert window.state=='idle' and window.border.phase=='idle' and window.border.isVisible()
        # Fullscreen uses inset bands/label, and must also obey native-failure fallback.
        window.fullscreen();assert window.border.isVisible()
        window._recording_transition=True;window.sync_overlay();assert not window.border.isVisible()
        window._recording_transition=False;window.sync_overlay()
        # OCR/picker temporarily suspend only the border; user preference persists.
        window.capture_pending=True;window.refresh();assert not window.border.isVisible()
        window.capture_pending=False;window.refresh();assert window.border.isVisible()
        window.close()
assert not errors,errors
print('Qt overlay states, synthetic drag/resize, live edit lock, toggle, pixel size and exclusion-failure fallback: PASS')
print('Native Windows visibility, mouse pass-through, DPI and actual gdigrab exclusion remain untested.')
