from pathlib import Path
import unittest
from unittest.mock import patch
from myrecorder.media import media_timing


class TimingTests(unittest.TestCase):
    def metadata(self,video='10',audio=None):
        streams=[{'codec_type':'video','duration':video}]
        if audio is not None:streams.append({'codec_type':'audio','duration':audio})
        return {'format':{'duration':video},'streams':streams}
    def test_video_only_duration(self):
        with patch('myrecorder.media.probe',return_value=self.metadata('12.5')):
            result=media_timing(Path('example.mp4'))
        self.assertEqual(result['video_duration'],12.5)
        self.assertIsNone(result['audio_duration'])
    def test_aac_rounding_is_not_reported_as_sync_failure(self):
        with patch('myrecorder.media.probe',return_value=self.metadata('10','10.02')):
            self.assertEqual(media_timing(Path('example.mp4'))['warnings'],[])
    def test_large_length_difference_warns(self):
        with patch('myrecorder.media.probe',return_value=self.metadata('10','11')):
            self.assertTrue(media_timing(Path('example.mp4'))['warnings'])
    def test_invalid_duration_does_not_pass(self):
        with patch('myrecorder.media.probe',return_value=self.metadata('nan')):
            with self.assertRaises(RuntimeError): media_timing(Path('example.mp4'))

    def test_nonfinite_audio_duration_warns_without_invalid_json(self):
        with patch('myrecorder.media.probe',return_value=self.metadata('10','nan')):
            result=media_timing(Path('example.mp4'))
        self.assertIsNone(result['audio_duration'])
        self.assertTrue(result['warnings'])


if __name__=='__main__': unittest.main()
