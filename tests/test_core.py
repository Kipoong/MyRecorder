import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from myrecorder.media import safe_title, publish, convert, probe, assemble, binary, run
from myrecorder.cli import repair_wav
import wave


class Names(unittest.TestCase):
    def test_windows_names(self):
        self.assertEqual(safe_title(' 강의: 1/2?* '), '강의 12')
        self.assertEqual(safe_title('CON.txt'), '_CON.txt')
        self.assertEqual(safe_title('...'), '녹화')
    def test_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p/'강의.mp4').write_bytes(b'original')
            (p/'tmp').write_bytes(b'new')
            self.assertEqual(publish(p/'tmp', p, '강의').name, '강의 (1).mp4')
            self.assertEqual((p/'강의.mp4').read_bytes(), b'original')
    def test_wav_repair(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'a.wav'
            with wave.open(str(p), 'wb') as f:
                f.setnchannels(1); f.setsampwidth(2); f.setframerate(48000)
                f.writeframes(b'\x00'*96000)
            with p.open('r+b') as f:
                f.seek(4); f.write(b'\x00'*4)
                f.seek(40); f.write(b'\x00'*4)
            repair_wav(p)
            with wave.open(str(p)) as f:
                self.assertEqual(f.getnframes(), 48000)


class MediaIntegration(unittest.TestCase):
    def test_mux_concat_and_speed(self):
        with tempfile.TemporaryDirectory(prefix='myrecorder-한글-') as d:
            root = Path(d)
            session = root/'session'; session.mkdir()
            segments=[]
            for i in range(2):
                run([binary('ffmpeg'), '-y', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=15:duration=1.5', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(session/f'{i:04d}.mkv')])
                tracks=[]
                for name, hz in [('system',440), ('mic',660)]:
                    filename=f'{i:04d}-{name}.wav'
                    run([binary('ffmpeg'), '-y', '-v', 'error', '-f', 'lavfi', '-i', f'sine=frequency={hz}:sample_rate=48000:duration=1.5', str(session/filename)])
                    tracks.append({'file':filename,'offset':0.05})
                segments.append({'index':i, 'tracks':tracks})
            # A failed start must not poison recovery of valid earlier segments.
            segments.append({'index':99,'tracks':[],'usable':False})
            (session/'session.json').write_text(json.dumps({'segments':segments}))
            original=assemble(session,root,'강의 테스트')
            result=probe(original)
            self.assertEqual({s['codec_type'] for s in result['streams']}, {'video','audio'})
            self.assertAlmostEqual(float(result['format']['duration']),3.0,delta=.25)
            converted_dir=root/'변환 결과'; converted_dir.mkdir()
            slowed=convert(original,2.0,1.0,converted_dir,session)
            self.assertEqual(slowed.parent, converted_dir)
            self.assertFalse(list(root.glob('.convert-*')))
            final=probe(slowed)
            self.assertTrue(original.exists())
            self.assertAlmostEqual(float(final['format']['duration']),float(result['format']['duration'])*2,delta=.5)
            streams={s['codec_type']:s for s in final['streams']}
            self.assertAlmostEqual(float(streams['video']['duration']),float(streams['audio']['duration']),delta=.25)
            run([binary('ffmpeg'),'-v','error','-i',str(slowed),'-f','null','-'])


if __name__ == '__main__':
    unittest.main()
