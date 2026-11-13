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

    def test_pause_elapsed_uses_measured_video_duration(self):
        recorder=Recorder(self.options)
        with patch('myrecorder.recorder.probe',return_value={'format':{'duration':'2.4'}}):
            recorder.start();recorder.pause();recorder.start();recorder.pause()
        self.assertAlmostEqual(recorder.elapsed,4.8)
        self.assertEqual([s['duration'] for s in recorder.manifest['segments']],[2.4,2.4])
    def test_success_marks_session_for_explicit_cleanup(self):
        self.options.title_source='window'
        recorder=Recorder(self.options);recorder.start();recorder.pause()
        output=self.options.folder/'Example.mp4';output.write_bytes(b'example media')
        timing={'video_duration':2.4,'audio_duration':None,'warnings':[]}
        with patch('myrecorder.recorder.assemble',return_value=output),patch('myrecorder.recorder.media_timing',return_value=timing):
            self.assertEqual(recorder.finish(),output)
        self.assertEqual(recorder.final_duration,2.4)
        self.assertEqual(recorder.manifest['status'],'saved')
        self.assertEqual(recorder.manifest['title_source'],'window')
        self.assertTrue((recorder.folder/'recording-events.jsonl').exists())
    def test_save_failure_keeps_raw_and_logs(self):
        recorder=Recorder(self.options);recorder.start();recorder.pause()
        raw=recorder.folder/'0000.mkv';raw.write_bytes(b'original')
        with patch('myrecorder.recorder.assemble',side_effect=OSError('full disk')):
            with self.assertRaisesRegex(RuntimeError,'recording-events.jsonl'):recorder.finish()
        self.assertEqual(raw.read_bytes(),b'original')
        self.assertEqual(recorder.manifest['status'],'save_failed')


if __name__=='__main__': unittest.main()
