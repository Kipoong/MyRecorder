"""WASAPI loopback / microphone capture. Imports Windows backend lazily."""
from pathlib import Path
import threading
import time
import wave


class AudioTrack:
    def __init__(self, path: Path, loopback: bool):
        import pyaudiowpatch as pa
        self.pa_module = pa
        self.pa = pa.PyAudio()
        self.stream = None
        self.wav = None
        self.error = None
        self.frames = 0
        self.started = 0.0
        self.path = path
        try:
            if loopback:
                device = self.pa.get_default_wasapi_loopback()
            else:
                device = self.pa.get_default_input_device_info()
            self.rate = int(device['defaultSampleRate'])
            self.channels = min(2, int(device['maxInputChannels']))
            if self.channels < 1:
                raise RuntimeError('입력 채널이 없는 장치입니다.')
            self.wav = wave.open(str(path), 'wb')
            self.wav.setnchannels(self.channels)
            self.wav.setsampwidth(2)
            self.wav.setframerate(self.rate)
            self.stream = self.pa.open(format=pa.paInt16, channels=self.channels, rate=self.rate,
                                       input=True, input_device_index=device['index'], frames_per_buffer=1024,
                                       stream_callback=self.callback, start=False)
        except BaseException:
            self.close()
            raise

    def callback(self, data, count, timing, status):
        try:
            if status:
                raise RuntimeError(f'오디오 버퍼 오류: {status}. 이 구간의 음성 누락 가능성이 있습니다.')
            if not self.started:
                self.started = time.monotonic() - count / self.rate
            self.wav.writeframesraw(data)
            self.frames += count
            return (None, self.pa_module.paContinue)
        except BaseException as exc:
            self.error = str(exc)
            return (None, self.pa_module.paAbort)

    def start(self):
        self.stream.start_stream()

    def close(self):
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
        if self.wav:
            self.wav.close()
            self.wav = None
        self.pa.terminate()
