import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from myrecorder.modes import RecordingPolicy
from myrecorder.preferences import PreferencesStore
from myrecorder.desktop import layout, validate_rect, bounding
from myrecorder.display import NativeMonitor, DisplayError
from myrecorder.settings import StorageError


def screen(name,rect,dpr=1):
    x,y,w,h=rect
    q=SimpleNamespace(x=lambda:x,y=lambda:y,width=lambda:w,height=lambda:h)
    return SimpleNamespace(name=lambda:name,geometry=lambda:q,devicePixelRatio=lambda:dpr)

class ModesTests(unittest.TestCase):
    def test_manual_pause_resume_in_both_modes(self):
        for mode in ['lecture','general']:
            policy=RecordingPolicy(mode)
            self.assertTrue(policy.permits('start','idle'))
            self.assertTrue(policy.permits('pause','recording'))
            self.assertTrue(policy.permits('resume','paused'))
            self.assertFalse(policy.permits('start','saving'))
            self.assertFalse(policy.automatic_detection_supported)
    def test_playback_stillness_silence_never_pause_automatically(self):
        for mode in ['lecture','general']:
            for event in ['source_paused','source_playing','silent','unchanged_frame','unknown_player']:
                self.assertEqual(RecordingPolicy(mode).playback_action(event),'continue')
    def test_mode_persists_without_touching_storage(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);settings=root/'settings.json';settings.write_bytes(b'personal example')
            store=PreferencesStore(root);self.assertEqual(store.load().mode,'lecture')
            store.save(RecordingPolicy('general'))
            self.assertEqual(PreferencesStore(root).load().mode,'general')
            self.assertEqual(settings.read_bytes(),b'personal example')
    def test_invalid_preference_is_preserved_and_reported(self):
        with tempfile.TemporaryDirectory() as d:
            store=PreferencesStore(d);store.path.write_text('{bad')
            with self.assertRaises(StorageError):store.load()
            self.assertEqual(store.path.read_text(),'{bad')
    def test_invalid_mode_rejected(self):
        with self.assertRaises(ValueError):RecordingPolicy('automatic')

class DesktopTests(unittest.TestCase):
    def fixtures(self):
        monitors=[NativeMonitor('Right',(0,0,1920,1080)),NativeMonitor('Left',(-1920,0,1920,1080))]
        screens=[screen('Left',(-1920,0,1920,1080)),screen('Right',(0,0,1920,1080))]
        return screens,monitors
    def test_two_screens_reverse_order_and_spanning_roi(self):
        screens,monitors=self.fixtures()
        with patch('myrecorder.desktop.native_monitors',return_value=monitors):
            entries,bounds,signature=layout(screens)
        self.assertEqual(bounds,(-1920,0,3840,1080))
        self.assertEqual(validate_rect((-200,100,800,513),bounds,monitors),(-200,100,800,513))
        self.assertEqual(validate_rect(bounds,bounds,monitors),bounds)
        self.assertEqual(entries[0][1].name,'Left')
    def test_mixed_dpi_keeps_physical_coordinates(self):
        for dpr in [1.25,1.5]:
            screens=[screen('Left',(-1920,0,round(1920/dpr),round(1080/dpr)),dpr),screen('Right',(0,0,1920,1080))]
            _,monitors=self.fixtures()
            with patch('myrecorder.desktop.native_monitors',return_value=monitors),patch('myrecorder.desktop.dpi_awareness',return_value=2):
                _,bounds,_=layout(screens)
            self.assertEqual(validate_rect((-100,0,200,300),bounds,monitors),(-100,0,200,300))
    def test_mixed_dpi_requires_awareness(self):
        screens=[screen('A',(0,0,1280,720),1.5)]
        with patch('myrecorder.desktop.native_monitors',return_value=[NativeMonitor('A',(0,0,1920,1080))]),patch('myrecorder.desktop.dpi_awareness',return_value=1):
            with self.assertRaises(DisplayError):layout(screens)
    def test_missing_screen_and_conflicting_identity_rejected(self):
        screens,monitors=self.fixtures()
        with patch('myrecorder.desktop.native_monitors',return_value=monitors[:1]):
            with self.assertRaises(DisplayError):layout(screens)
        monitors[0]=NativeMonitor('Right',(100,0,1920,1080))
        with patch('myrecorder.desktop.native_monitors',return_value=monitors):
            with self.assertRaises(DisplayError):layout(screens)
    def test_gaps_and_outside_rect(self):
        monitors=[NativeMonitor('A',(0,0,100,100)),NativeMonitor('B',(200,0,100,100))]
        bounds=bounding([m.rect for m in monitors])
        with self.assertRaises(DisplayError):validate_rect((120,0,50,50),bounds,monitors)
        with self.assertRaises(DisplayError):validate_rect((-1,0,10,10),bounds,monitors)
        self.assertEqual(validate_rect((50,0,200,50),bounds,monitors),(50,0,200,50))

if __name__=='__main__':unittest.main()
