"""Offscreen Qt boundary/logging tests; not a native Windows display test."""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtCore import QRect, QPointF
from PySide6.QtWidgets import QApplication
from myrecorder.gui import Window, RegionPicker
from myrecorder.settings import SettingsStore, StoragePaths
from myrecorder.display import NativeMonitor, screen_snapshot, DisplayError

app=QApplication([]);app.setQuitOnLastWindowClosed(False)
screen=app.primaryScreen();bounds=screen.geometry()
with tempfile.TemporaryDirectory(prefix='display-example-') as folder:
    root=Path(folder);project=root/'project';project.mkdir()
    store=SettingsStore(project)
    store.save(StoragePaths(*(str(root/name) for name in ('Recordings','Converted','Temp'))))
    native=NativeMonitor('Example Native',(bounds.x(),bounds.y(),bounds.width(),bounds.height()),primary=True)
    with patch('myrecorder.display.native_monitors',return_value=[native]):
        window=Window(store,check_startup=False)
        window.set_region(QRect(bounds.x()+50,bounds.y()+50,200,150),screen)
        window.map_selected('test_selection')
        with patch('myrecorder.gui.QMessageBox.information') as info:
            window.diagnose_display()
            assert info.called
        log=window.coordinate_log.path
        events=[json.loads(line) for line in log.read_text().splitlines()]
        mapped=[event for event in events if event.get('event')=='display_mapping_ok']
        assert mapped and mapped[-1]['matching']['strategy']=='unique_geometry'
        assert 'windows_monitors' in mapped[-1] and 'qt_screens' in mapped[-1]
        # Outer overlay decoration never changes the selected capture rectangle.
        assert window.border.selected==window.region
        assert window.border.physical==(bounds.x()+50,bounds.y()+50,200,150)
        window.set_region(QRect(bounds.right()-5,bounds.y(),100,100),screen)
        with patch('myrecorder.gui.Recorder') as recorder,patch('myrecorder.gui.QMessageBox.warning') as warning:
            window.start();recorder.assert_not_called();assert warning.called
        events=[json.loads(line) for line in log.read_text().splitlines()]
        assert any(e.get('operation')=='recording_start' and e.get('failed_condition')=='REGION_OUTSIDE_MONITOR' for e in events)
        window.set_region(QRect(bounds.x()+20,bounds.y()+20,100,100),screen)
        window.selected_screen_identity={**screen_snapshot(screen),'name':'Example previous screen'}
        with patch('myrecorder.gui.Recorder') as recorder,patch('myrecorder.gui.QMessageBox.warning'):
            window.start();recorder.assert_not_called()
        assert 'SCREEN_LAYOUT_CHANGED' in log.read_text()
        window.close()
    # Drag far past northwest edge: selection is clamped, release recomputes even without move.
    picker=RegionPicker(screen)
    event=lambda x,y:SimpleNamespace(position=lambda:QPointF(x,y))
    results=[];picker.selected.connect(results.append)
    picker.mousePressEvent(event(120,100));picker.mouseReleaseEvent(event(-100,-100))
    assert results==[QRect(bounds.x(),bounds.y(),120,100)]
    picker=RegionPicker(screen);results=[];picker.selected.connect(results.append)
    picker.mousePressEvent(event(0,0));picker.mouseReleaseEvent(event(bounds.width()+100,bounds.height()+100))
    assert results==[bounds]
print('Qt picker clamping, selection identity, coordinate logs and fail-before-Recorder: PASS')
print('Native dual monitor/DPI/capture matching remains untested on Windows.')
