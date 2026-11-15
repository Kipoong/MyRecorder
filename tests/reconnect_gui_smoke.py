"""Qt startup restoration is simulated; no real DPAPI or Windows device test."""
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
from PySide6.QtWidgets import QApplication,QMessageBox
from myrecorder.gui import Window
from myrecorder.settings import SettingsStore,StoragePaths
from myrecorder.pairing_store import PairingStore
from test_pairing_store import Cipher
app=QApplication([]);app.setQuitOnLastWindowClosed(False)
with tempfile.TemporaryDirectory(prefix='reconnect-gui-') as d:
    root=Path(d);project=root/'project';project.mkdir();settings=SettingsStore(project)
    settings.save(StoragePaths(*(str(root/k) for k in ['Recordings','Converted','Temp'])))
    store=PairingStore(root/'credentials.dpapi',Cipher())
    with patch('myrecorder.gui.physical_region',return_value=(0,0,320,180)),patch('myrecorder.gui.Recorder') as engine:
        first=Window(settings,check_startup=False);first.pairing_store=store
        first.extension_id.setText('a'*32)
        with patch('myrecorder.gui.os',SimpleNamespace(name='nt')):first.open_browser_bridge()
        pairing=first.browser_bridge.pairing;first.close()
        second=Window(settings,check_startup=False);second.pairing_store=store
        with patch('myrecorder.gui.os',SimpleNamespace(name='nt')):second.restore_browser_pairing()
        assert second.browser_bridge.pairing==pairing
        assert second.state=='idle' and second.recorder is None and second.auto_link is None
        assert not second.auto_detect.isChecked() and not second.browser_bridge.armed
        assert second.pairing_info.text()==''
        import json
        clipboard=Mock()
        with patch('myrecorder.gui.QApplication.clipboard',return_value=clipboard):second.copy_browser_pairing()
        assert json.loads(clipboard.setText.call_args.args[0])==pairing
        assert second.pairing_info.text()==''
        engine.assert_not_called()
        with patch('myrecorder.gui.QMessageBox.question',return_value=QMessageBox.Yes):second.reset_browser_pairing()
        assert not store.path.exists() and second.browser_bridge is None
        assert second.extension_id.isEnabled() and second.bridge_button.isEnabled()
        second.close()
print('Qt simulated encrypted pairing restore, no capture/auto-arm, explicit reset: PASS')
