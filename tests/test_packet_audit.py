import io
import unittest
from unittest.mock import patch
from myrecorder.timestamps import packet_audit

class PacketAuditTests(unittest.TestCase):
    def process(self,lines):
        class Process:
            stdout=io.StringIO(lines);stderr=io.StringIO('')
            def wait(self,timeout=None):return 0
            def poll(self):return 0
        return Process()
    def test_pts_reordering_for_b_frames_is_valid(self):
        text='stream_index=0|pts_time=0.1|dts_time=-0.1|duration_time=0.1\nstream_index=0|pts_time=0|dts_time=0|duration_time=0.1\n'
        with patch('myrecorder.timestamps.subprocess.Popen',return_value=self.process(text)),patch('myrecorder.timestamps.binary',return_value='example'):
            report=packet_audit('example.mp4')
        self.assertFalse(report['warnings'])
    def test_dts_regression_and_long_gap_warn(self):
        text='stream_index=0|pts_time=0|dts_time=0|duration_time=0.1\nstream_index=0|pts_time=0.1|dts_time=-0.2|duration_time=0.1\nstream_index=0|pts_time=1|dts_time=1|duration_time=0.1\n'
        with patch('myrecorder.timestamps.subprocess.Popen',return_value=self.process(text)),patch('myrecorder.timestamps.binary',return_value='example'):
            report=packet_audit('example.mp4')
        self.assertEqual(report['streams']['0']['dts_regressions'],1)
        self.assertEqual(len(report['warnings']),2)
    def test_missing_pts_warns(self):
        with patch('myrecorder.timestamps.subprocess.Popen',return_value=self.process('stream_index=0|pts_time=N/A|dts_time=0\n')),patch('myrecorder.timestamps.binary',return_value='example'):
            self.assertTrue(packet_audit('example.mp4')['warnings'])

if __name__=='__main__':unittest.main()
