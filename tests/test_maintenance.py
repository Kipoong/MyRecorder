import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from myrecorder.maintenance import saved_sessions, cleanup_sessions


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='cleanup example ');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.sessions=self.root/'Temp';self.sessions.mkdir()
        self.output=self.root/'Recordings'/'Example.mp4';self.output.parent.mkdir();self.output.write_bytes(b'final-video')
        self.session=self.sessions/('session-'+'a'*32);self.session.mkdir()
        self.raw=self.session/'0000.mkv';self.raw.write_bytes(b'original-capture')
        self.data={'owner':'MyRecorder','status':'saved','recordings_folder':str(self.output.parent),
                   'segments':[{'complete':True}],
                   'output':{'path':str(self.output),'size':self.output.stat().st_size}}
        self.save()
        patcher=patch('myrecorder.maintenance.probe',return_value={'streams':[{'codec_type':'video'}]})
        patcher.start();self.addCleanup(patcher.stop)
    def save(self): (self.session/'session.json').write_text(json.dumps(self.data))
    def test_completed_preview_and_cleanup_keep_mp4(self):
        candidates=saved_sessions(self.sessions)
        self.assertEqual(len(candidates),1)
        self.assertGreater(candidates[0].bytes,0)
        self.assertEqual(cleanup_sessions(self.sessions,[self.session]),[self.session])
        self.assertEqual(self.output.read_bytes(),b'final-video')
    def test_failed_session_is_never_deleted(self):
        self.data['status']='save_failed';self.save()
        self.assertEqual(saved_sessions(self.sessions),[])
        with self.assertRaises(RuntimeError): cleanup_sessions(self.sessions,[self.session])
        self.assertTrue(self.raw.exists())
    def test_old_unknown_session_is_preserved(self):
        del self.data['owner'];self.save()
        self.assertEqual(saved_sessions(self.sessions),[])
        self.assertTrue(self.raw.exists())
    def test_missing_or_modified_output_is_preserved(self):
        self.output.write_bytes(b'changed-file-size')
        with self.assertRaises(RuntimeError): cleanup_sessions(self.sessions,[self.session])
        self.assertTrue(self.raw.exists())
        self.output.unlink();self.assertEqual(saved_sessions(self.sessions),[])
    def test_probe_failure_preserves_original(self):
        with patch('myrecorder.maintenance.probe',side_effect=RuntimeError('corrupt MP4')):
            self.assertEqual(saved_sessions(self.sessions),[])
        self.assertTrue(self.raw.exists())
    def test_symlink_child_and_outside_folder_are_rejected(self):
        outside=self.root/'outside';outside.mkdir();(outside/'keep').write_text('safe')
        try: (self.session/'linked').symlink_to(outside,target_is_directory=True)
        except OSError: self.skipTest('symlinks unavailable')
        self.assertEqual(saved_sessions(self.sessions),[])
        with self.assertRaises(RuntimeError): cleanup_sessions(self.sessions,[outside])
        self.assertTrue((outside/'keep').exists())
    def test_revalidates_after_preview(self):
        self.assertEqual(len(saved_sessions(self.sessions)),1)
        self.data['status']='recording';self.save()
        with self.assertRaises(RuntimeError): cleanup_sessions(self.sessions,[self.session])
        self.assertTrue(self.raw.exists())

    def test_output_inside_session_is_never_deleted(self):
        final=self.session/'final.mp4';final.write_bytes(b'final-video')
        self.data['recordings_folder']=str(self.session)
        self.data['output']['path']=str(final);self.save()
        self.assertEqual(saved_sessions(self.sessions),[])
        self.assertTrue(final.exists())
    def test_session_with_failed_segment_is_preserved(self):
        self.data['segments'].append({'complete':False,'startup_error':'example failure'});self.save()
        self.assertEqual(saved_sessions(self.sessions),[])
        self.assertTrue(self.raw.exists())

    def test_malformed_metadata_is_preserved_without_crashing_preview(self):
        for data in [[],{'owner':'MyRecorder','status':'saved','segments':[123]}]:
            (self.session/'session.json').write_text(json.dumps(data))
            self.assertEqual(saved_sessions(self.sessions),[])
            self.assertTrue(self.raw.exists())


if __name__=='__main__': unittest.main()
