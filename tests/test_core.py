import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from myrecorder.media import safe_title, publish, convert, probe, assemble, binary, run, media_timing
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

    def test_saved_session_cleanup_with_real_mp4(self):
        from myrecorder.maintenance import saved_sessions, cleanup_sessions
        with tempfile.TemporaryDirectory(prefix='real-cleanup-') as directory:
            root=Path(directory);temp=root/'Temp';temp.mkdir()
            session=temp/('session-'+'b'*32);session.mkdir()
            destination=root/'Recordings';destination.mkdir()
            run([binary('ffmpeg'),'-y','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=15:duration=1',
                 '-c:v','libx264','-pix_fmt','yuv420p',str(session/'0000.mkv')])
            data={'version':3,'owner':'MyRecorder','status':'paused','recordings_folder':str(destination),
                  'segments':[{'index':0,'tracks':[],'complete':True,'usable':True}]}
            manifest=session/'session.json';manifest.write_text(json.dumps(data))
            output=assemble(session,destination,'Example Lecture')
            timing=media_timing(output)
            self.assertAlmostEqual(timing['video_duration'],1,delta=.1)
            self.assertIsNone(timing['audio_duration'])
            self.assertEqual(saved_sessions(temp),[])
            data.update(status='saved',output={'path':str(output),'size':output.stat().st_size,**timing})
            manifest.write_text(json.dumps(data))
            self.assertEqual(len(saved_sessions(temp)),1)
            cleanup_sessions(temp,[session])
            self.assertFalse(session.exists())
            self.assertTrue(output.exists())
            self.assertEqual(probe(output)['streams'][0]['codec_type'],'video')




class ConsecutiveMediaTests(unittest.TestCase):
    def test_three_real_mp4_saves_keep_previous_outputs_and_audio(self):
        import hashlib
        import shutil
        with tempfile.TemporaryDirectory(prefix='continuous media 한글 ') as d:
            root=Path(d);destination=root/'Recordings';destination.mkdir()
            video=root/'sample.mkv';audio=root/'sample.wav'
            run([binary('ffmpeg'),'-y','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=15:duration=0.6',
                 '-c:v','libx264','-pix_fmt','yuv420p',str(video)])
            run([binary('ffmpeg'),'-y','-v','error','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=0.6',str(audio)])
            hashes={}
            for index in range(3):
                session=root/f'session-{index}';session.mkdir()
                shutil.copyfile(video,session/'0000.mkv');shutil.copyfile(audio,session/'system.wav')
                (session/'session.json').write_text(json.dumps({'segments':[{'index':0,'usable':True,
                    'tracks':[{'file':'system.wav','offset':0.}]}]}))
                result=assemble(session,destination,'Example Lecture')
                self.assertNotIn(result,hashes)
                hashes[result]=hashlib.sha256(result.read_bytes()).hexdigest()
                self.assertEqual({s['codec_type'] for s in probe(result)['streams']},{'audio','video'})
                timing=media_timing(result)
                self.assertAlmostEqual(timing['video_duration'],timing['audio_duration'],delta=.25)
                run([binary('ffmpeg'),'-v','error','-i',str(result),'-f','null','-'])
                for path,digest in hashes.items():
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),digest)
            self.assertEqual(len(list(destination.glob('*.mp4'))),3)


if __name__=='__main__':unittest.main()
