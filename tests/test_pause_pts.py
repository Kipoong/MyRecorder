"""Six synthetic segments model five manual pauses; no Windows capture claimed."""
import json
import shutil
import tempfile
from pathlib import Path
import unittest
from myrecorder.media import run, binary, assemble, media_timing, probe
from myrecorder.timestamps import packet_audit

class PauseTimestampTests(unittest.TestCase):
    def test_five_pauses_one_mp4_pts_and_audio_continuity(self):
        import array
        with tempfile.TemporaryDirectory(prefix='five-pause-') as d:
            root=Path(d);session=root/'session';session.mkdir();destination=root/'Recordings';destination.mkdir()
            source=root/'source.mkv';tone=root/'tone.wav'
            run([binary('ffmpeg'),'-y','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=15:duration=0.6',
                 '-c:v','libx264','-pix_fmt','yuv420p',str(source)])
            run([binary('ffmpeg'),'-y','-v','error','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=0.6',str(tone)])
            segments=[]
            for index in range(6):
                shutil.copyfile(source,session/f'{index:04d}.mkv');shutil.copyfile(tone,session/f'{index:04d}.wav')
                segments.append({'index':index,'usable':True,'duration':.6,'tracks':[{'file':f'{index:04d}.wav','offset':0}]})
            (session/'session.json').write_text(json.dumps({'segments':segments}))
            output=assemble(session,destination,'Example Lecture')
            self.assertEqual(len(list(destination.glob('*.mp4'))),1)
            timing=media_timing(output)
            self.assertAlmostEqual(timing['video_duration'],3.6,delta=.12)
            self.assertAlmostEqual(timing['video_duration'],timing['audio_duration'],delta=.12)
            final=packet_audit(output)
            self.assertFalse(final['warnings'],final)
            self.assertEqual(len(final['streams']),2)
            for state in final['streams'].values():self.assertEqual(state['dts_regressions'],0)
            for path in sorted(session.glob('*-ready.mp4')):
                audit=packet_audit(path);self.assertFalse(audit['warnings'],audit)
            self.assertEqual(len(list(session.glob('*-pts.json'))),6)
            pcm=root/'audio.pcm'
            run([binary('ffmpeg'),'-y','-v','error','-i',str(output),'-map','0:a:0','-ac','1','-ar','48000','-f','s16le',str(pcm)])
            samples=array.array('h',pcm.read_bytes())
            # Each 50ms join window must contain tone; detects inserted long silence.
            for index in range(1,6):
                center=round(index*.6*48000);part=samples[center-1200:center+1200]
                self.assertGreater(sum(v*v for v in part)/len(part),100000)
            run([binary('ffmpeg'),'-v','error','-i',str(output),'-f','null','-'])

if __name__=='__main__':unittest.main()
