import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import wave
from unittest.mock import patch
from myrecorder.audio import (AudioTrack, AudioError, Diagnostics, TimedPCM, device_choices,
                              inventory, select_pair)


def device(index, name, inputs=0, outputs=0, loop=False, host=7, rate=48000):
    return dict(index=index, name=name, maxInputChannels=inputs, maxOutputChannels=outputs,
                isLoopbackDevice=loop, hostApi=host, defaultSampleRate=rate)


class Stream:
    def __init__(self, module, args):
        self.module, self.args = module, args
        self.active = False
        self.closed = False
    def get_input_latency(self): return 0.01
    def start_stream(self):
        self.module.native_threads.append(threading.get_ident())
        if self.module.start_failure: raise OSError('start failed')
        self.active = True
    def is_active(self):
        self.module.native_threads.append(threading.get_ident())
        return self.active
    def stop_stream(self): self.active = False
    def close(self):
        self.module.native_threads.append(threading.get_ident())
        self.closed = True; self.active = False
    def send(self, data, frames, timing=None, status=0):
        result=self.args['stream_callback'](data, frames, timing or {}, status)
        if result[1]==self.module.paAbort: self.active=False
        return result


class PA:
    def __init__(self, module):
        self.module=module
        module.native_threads.append(threading.get_ident())
    def get_host_api_info_by_type(self, value): return {'index':7,'name':'Windows WASAPI','defaultOutputDevice':1}
    def get_device_count(self): return len(self.module.devices)
    def get_device_info_by_index(self, index): return self.module.devices[index]
    def get_default_output_device_info(self): return self.module.devices[0]  # non-WASAPI default must not win
    def get_default_input_device_info(self): return self.module.devices[7]
    def is_format_supported(self, rate, **args):
        if (rate,args['input_channels']) not in self.module.formats: raise ValueError('unsupported',-9997)
        return True
    def open(self, **args):
        self.module.native_threads.append(threading.get_ident())
        if self.module.open_failure: raise OSError('exclusive/busy')
        self.module.open_args=args
        self.module.stream=Stream(self.module,args)
        return self.module.stream
    def terminate(self):
        self.module.native_threads.append(threading.get_ident())
        self.module.terminated+=1


class Module:
    # Entirely synthetic fixtures; no real user device data.
    paWASAPI=13; paInt16=8; paContinue=0; paAbort=2
    def __init__(self):
        self.devices=[device(0,'MME Other',outputs=2,host=0),
                      device(1,'Example Speakers',outputs=2),
                      device(2,'Example HDMI Output',outputs=2),
                      device(3,'Example Speakers [Loopback]',inputs=2,loop=True),
                      device(4,'Example HDMI Output [Loopback]',inputs=2,loop=True),
                      device(5,'Example Digital Output',outputs=2),
                      device(6,'Example Digital Output [Loopback]',inputs=2,loop=True),
                      device(7,'Microphone',inputs=1,host=0)]
        self.formats={(48000,2),(48000,1)}
        self.native_threads=[]
        self.terminated=0; self.open_failure=False; self.start_failure=False
    def PyAudio(self): return PA(self)
    def get_portaudio_version_text(self): return 'mock PortAudio; not Windows runtime'


class AudioTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='audio 한글 ')
        self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.module=Module()
        self.log=Diagnostics(self.folder/'diagnostics.jsonl')
    def make_track(self, **args):
        track=AudioTrack(self.folder/'test.wav',True,log=self.log,module=self.module,**args)
        self.addCleanup(track.close)
        return track
    def test_native_lifecycle_uses_one_persistent_thread(self):
        track=self.make_track();track.start();track.snapshot();track.close()
        self.assertEqual(len(set(self.module.native_threads)),1)
        self.assertNotEqual(self.module.native_threads[0],threading.get_ident())

    def test_default_pairs_wasapi_speaker_not_mme(self):
        choices=device_choices(self.log,self.module)
        selected=next(c for c in choices if c['default'])
        self.assertEqual(selected['index'],1)
        self.assertEqual(selected['loopback_index'],3)
        track=self.make_track()
        self.assertEqual(self.module.open_args['input_device_index'],3)
        self.assertEqual(track.channels,2)
        self.assertEqual(track.rate,48000)
    def test_manual_hdmi_pairs_its_loopback(self):
        track=self.make_track(selection={'index':2,'name':self.module.devices[2]['name']})
        self.assertEqual(self.module.open_args['input_device_index'],4)
    def test_missing_loopback_diagnosis(self):
        self.module.devices[3]['name']='Unrelated [Loopback]'
        with self.assertRaisesRegex(AudioError,'LOOPBACK_NOT_FOUND'): self.make_track()
        self.assertEqual(self.module.terminated,1)
        self.assertIn('initialization_failed',(self.folder/'diagnostics.jsonl').read_text())
    def test_ambiguous_names_do_not_guess(self):
        self.module.devices[4]['name']=self.module.devices[3]['name']
        with self.assertRaisesRegex(AudioError,'LOOPBACK_AMBIGUOUS'): self.make_track()
    def test_stale_id_does_not_choose_another_device(self):
        with self.assertRaisesRegex(AudioError,'DEVICE_CHANGED'):
            self.make_track(selection={'index':2,'name':'Old HDMI'})
    def test_no_wasapi_default(self):
        info=inventory(PA(self.module),self.module,self.log)
        info['default_output_index']=-1
        with self.assertRaisesRegex(AudioError,'OUTPUT_NOT_FOUND'): select_pair(info)
    def test_exact_name_avoids_substring_mapping(self):
        info=inventory(PA(self.module),self.module,self.log)
        info['loopbacks'][0]['name']='Example Speakers Extra [Loopback]'
        with self.assertRaisesRegex(AudioError,'LOOPBACK_NOT_FOUND'): select_pair(info)
    def test_format_fallback(self):
        self.module.devices[3].update(maxInputChannels=6,defaultSampleRate=96000)
        track=self.make_track()
        self.assertEqual((track.rate,track.channels),(48000,2))
        self.assertIn('format_probe',(self.folder/'diagnostics.jsonl').read_text())
    def test_unsupported_format_is_not_open_failure(self):
        self.module.formats=set()
        with self.assertRaisesRegex(AudioError,'FORMAT_UNSUPPORTED'): self.make_track()
    def test_open_failure_preserves_wav_and_diagnostics(self):
        self.module.open_failure=True
        with self.assertRaisesRegex(AudioError,'DEVICE_OPEN_FAILED'): self.make_track()
        with wave.open(str(self.folder/'test.wav')) as wav:
            self.assertEqual(wav.getnchannels(),2)
        self.assertEqual(self.module.terminated,1)
    def test_no_packets_is_pending_then_timeout_not_false_silence(self):
        track=self.make_track();track.start()
        self.assertEqual(track.wait_ready(.01)['state'],'WAITING')
        self.assertEqual(track.snapshot(track.started+9)['state'],'NO_DATA_TIMEOUT')
        self.assertIsNone(track.error)
        track.close()
        with wave.open(str(track.path)) as wav: self.assertGreater(wav.getnframes(),0)
    def test_delayed_data_recovers_from_timeout(self):
        track=self.make_track(); track.start()
        self.assertEqual(track.snapshot(track.started+9)['state'],'NO_DATA_TIMEOUT')
        timer=threading.Timer(.06,lambda:self.module.stream.send(b'\x01\x00'*128,64))
        timer.start()
        try: self.assertEqual(track.wait_ready(.5)['state'],'RECEIVING')
        finally: timer.join()
        track.close()
        self.assertEqual(track.received_frames,64)
        self.assertGreaterEqual(track.frames,64)
    def test_received_zero_pcm_is_measured_silence(self):
        track=self.make_track();track.start()
        self.module.stream.send(bytes(1024*4),1024)
        self.assertEqual(track.wait_ready(.1)['state'],'SILENT')
        track.close()
        self.assertEqual(track.received_frames,1024)
    def test_stopped_stream_is_error(self):
        track=self.make_track();track.start();self.module.stream.active=False
        self.assertEqual(track.snapshot()['state'],'ERROR')
        self.assertIn('STREAM_STOPPED',track.snapshot()['detail'])
    def test_buffer_flag_is_reported_without_discarding_audio(self):
        track=self.make_track();track.start()
        self.module.stream.send(b'\x01\x00'*128,64,status=2)
        self.assertEqual(track.wait_ready(.1)['state'],'BUFFER_WARNING')
        track.close();self.assertGreaterEqual(track.frames,64)
    def test_queue_overflow_is_error_not_silence(self):
        track=self.make_track();track.started=time.monotonic()
        for _ in range(257): self.module.stream.send(b'\x01\x00'*2,1)
        self.assertIn('BUFFER_OVERFLOW',track.error)
    def test_writer_failure_is_reported(self):
        track=self.make_track()
        with patch.object(track.sink,'write',side_effect=OSError('disk full')):
            track.start();self.module.stream.send(b'\x01\x00'*128,64)
            deadline=time.monotonic()+1
            while not track.error and time.monotonic()<deadline: time.sleep(.01)
            self.assertIn('AUDIO_WRITE_FAILED',track.error)
        track.close()
    def test_diagnostics_failure_does_not_skip_device_cleanup(self):
        track=self.make_track();track.start()
        self.log.path=self.folder  # a directory cannot be opened as a log file
        track.snapshot()
        self.assertEqual(track.snapshot()['state'],'ERROR')
        track.close()
        self.assertTrue(self.module.stream.closed)
        self.assertEqual(self.module.terminated,1)
    def test_diagnostics_unwritable_location_is_explicit(self):
        with self.assertRaisesRegex(AudioError,'DIAGNOSTICS_WRITE_FAILED'):
            Diagnostics(self.folder/'missing-parent'/'log.jsonl')

    def test_adc_current_time_compensates_callback_latency(self):
        track=self.make_track();track.start();base=track.started
        with patch('myrecorder.audio.time.monotonic',return_value=base+.6):
            self.module.stream.send(bytes(4800*4),4800,{'input_buffer_adc_time':100.0,'current_time':100.5})
        track.close()
        self.assertAlmostEqual(track.first_position,4800,delta=1)
        self.assertEqual(track.timestamp_source,'adc-current_time')

    def test_adc_timestamps_preserve_missing_interval(self):
        track=self.make_track();track.start();base=track.started
        with patch('myrecorder.audio.time.monotonic',side_effect=[base+.1,base+2.1]):
            self.module.stream.send(bytes(4800*4),4800,{'input_buffer_adc_time':100.0})
            self.module.stream.send(b'\x01\x00'*9600,4800,{'input_buffer_adc_time':102.0})
        track.close()
        self.assertGreaterEqual(track.frames,100800)
        self.assertGreaterEqual(track.sink.padded_frames,91200)


class PCMTests(unittest.TestCase):
    def test_gap_is_silence_not_time_compression(self):
        data=io.BytesIO()
        wav=wave.open(data,'wb');wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(1000)
        sink=TimedPCM(wav,1000,1)
        sink.write(b'\x01\x00'*100,0);sink.write(b'\x02\x00'*100,1100)
        wav.close();data.seek(0)
        with wave.open(data) as reader:
            self.assertEqual(reader.getnframes(),1200)
            pcm=reader.readframes(1200)
        self.assertEqual(pcm[200:2200],bytes(2000))
        self.assertEqual(pcm[2200:],b'\x02\x00'*100)


if __name__=='__main__': unittest.main()
