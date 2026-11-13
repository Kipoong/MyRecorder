import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from myrecorder.recorder import Recorder, Options


class Process:
    def __init__(self,*args,**kwargs): self.returncode=None
    def poll(self): return self.returncode
    def communicate(self,data,timeout): self.returncode=0


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.options=Options(self.root/'Recordings','테스트',(0,0,320,180),
            temp_folder=self.root/'Temp',converted_folder=self.root/'Converted',system=False,mic=False)
        for target,replacement in [('os',SimpleNamespace(name='nt',replace=os.replace,fsync=os.fsync)),
                                   ('subprocess.Popen',Process),('time.sleep',lambda _:None)]:
            patcher=patch('myrecorder.recorder.'+target,replacement)
            patcher.start();self.addCleanup(patcher.stop)
    def test_video_only_never_initializes_audio(self):
        with patch('myrecorder.recorder.AudioTrack',side_effect=AssertionError('must not load audio')) as audio:
            recorder=Recorder(self.options);recorder.start();recorder.pause()
            audio.assert_not_called()
        self.assertTrue(recorder.manifest['segments'][0]['complete'])
        self.assertEqual(recorder.manifest['segments'][0]['tracks'],[])
        self.assertEqual(recorder.folder.parent,self.options.temp_folder)
    def test_failed_audio_start_saves_log_and_manifest(self):
        self.options.system=True
        with patch('myrecorder.recorder.AudioTrack',side_effect=RuntimeError('[DEVICE_OPEN_FAILED] busy')):
            recorder=Recorder(self.options)
            with self.assertRaisesRegex(RuntimeError,'audio-diagnostics.jsonl'): recorder.start()
        saved=json.loads((recorder.folder/'session.json').read_text())
        self.assertFalse(saved['segments'][0]['usable'])
        self.assertIn('DEVICE_OPEN_FAILED',saved['segments'][0]['startup_error'])
        self.assertTrue((recorder.folder/'audio-diagnostics.jsonl').exists())
        self.assertIsNone(recorder.process)
    def test_repeated_pause_retains_recorded_track_metadata(self):
        recorder=Recorder(self.options);recorder.start();recorder.pause()
        recorder.segment['tracks']=[{'file':'previous.wav','offset':.01}]
        recorder.pause()
        self.assertEqual(recorder.segment['tracks'][0]['file'],'previous.wav')


if __name__=='__main__': unittest.main()
