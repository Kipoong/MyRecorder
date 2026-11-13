"""WASAPI endpoint mapping, bounded callback queue, timed PCM and local diagnostics.
The Windows backend is lazy: video-only recording never imports PyAudioWPatch.
"""
from __future__ import annotations
import json
from concurrent.futures import Future
from . import __version__
import math
from pathlib import Path
import platform
import queue
import re
import threading
import time
import wave

STARTUP_GRACE = 8.0


class AudioError(RuntimeError):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(f'[{code}] {detail}')


class Diagnostics:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.error = None
        self.write('environment', app_version=__version__, system=platform.system(), release=platform.release(), version=platform.version(),
                   python=platform.python_version(), machine=platform.machine())
        if self.error:
            raise AudioError('DIAGNOSTICS_WRITE_FAILED', self.error)

    def write(self, event, **fields):
        # Logging failure must never interrupt device/WAV cleanup or replace the
        # original capture exception. Surface it on the next health check instead.
        try:
            with self.lock:
                with self.path.open('a', encoding='utf-8') as f:
                    f.write(json.dumps({'time': time.time(), 'event': event, **fields}, ensure_ascii=False, default=str)+'\n')
        except OSError as exc:
            self.error = f'진단 로그를 쓸 수 없습니다: {self.path}: {exc}'


def backend():
    try:
        import pyaudiowpatch as pa
        return pa
    except (ImportError, OSError) as exc:
        raise AudioError('BACKEND_UNAVAILABLE', f'PyAudioWPatch를 불러올 수 없습니다. install.bat과 Python 3.12 x64를 확인하세요. {exc}') from exc


def _name(name):
    return re.sub(r'\s*\[loopback\]\s*$', '', str(name), flags=re.I).strip().casefold()


def inventory(pa, module, log):
    try:
        host = dict(pa.get_host_api_info_by_type(module.paWASAPI))
        devices = [dict(pa.get_device_info_by_index(i)) for i in range(pa.get_device_count())]
    except Exception as exc:
        raise AudioError('DEVICE_DISCOVERY_FAILED', f'WASAPI 장치 목록을 읽을 수 없습니다: {exc}') from exc
    host_index = int(host['index'])
    outputs = [d for d in devices if d['hostApi'] == host_index and d.get('maxOutputChannels', 0) > 0 and not d.get('isLoopbackDevice')]
    loops = [d for d in devices if d['hostApi'] == host_index and d.get('isLoopbackDevice') and d.get('maxInputChannels', 0) > 0]
    try:
        normal_default = dict(pa.get_default_output_device_info())
    except Exception as exc:
        normal_default = {'error': str(exc)}
    result = {'host_api': host, 'default_output_index': int(host.get('defaultOutputDevice', -1)),
              'general_default_output': normal_default, 'devices': devices, 'outputs': outputs, 'loopbacks': loops}
    log.write('device_inventory', **result)
    return result


def select_pair(info, selection=None):
    outputs = info['outputs']
    index = info['default_output_index'] if selection is None else int(selection['index'])
    candidates = [d for d in outputs if int(d['index']) == index]
    if len(candidates) != 1:
        raise AudioError('OUTPUT_NOT_FOUND', 'WASAPI 기본/선택 출력 장치가 없습니다. 장치 목록을 새로고침하고 실제 재생 중인 스피커를 선택하세요.')
    output = candidates[0]
    if selection is not None and output['name'] != selection['name']:
        raise AudioError('DEVICE_CHANGED', '선택 후 장치 ID가 변경되었습니다. 장치 목록을 새로고침하세요.')
    # The pinned PyAudioWPatch helper uses substring matching. Exact normalized names
    # avoid matching e.g. Speakers to Speakers (HDMI). Ambiguous names must not guess.
    loops = [d for d in info['loopbacks'] if _name(d['name']) == _name(output['name'])]
    if not loops:
        raise AudioError('LOOPBACK_NOT_FOUND', f"출력 '{output['name']}' (ID {index})에 대응하는 WASAPI Loopback 입력이 없습니다.")
    if len(loops) > 1:
        raise AudioError('LOOPBACK_AMBIGUOUS', f"'{output['name']}'의 Loopback 이름이 중복되어 안전하게 연결할 수 없습니다. Windows에서 장치 이름을 구분해 주세요.")
    return output, loops[0]


def device_choices(log, module=None):
    module = module or backend()
    pa = None
    try:
        pa = module.PyAudio()
        info = inventory(pa, module, log)
        choices = []
        for output in info['outputs']:
            selection = {'index': int(output['index']), 'name': output['name']}
            try:
                _, loop = select_pair(info, selection)
                selection.update(loopback_index=int(loop['index']), channels=int(loop['maxInputChannels']),
                                 rate=int(loop['defaultSampleRate']), available=True)
            except AudioError as exc:
                selection.update(available=False, reason=str(exc))
            selection['default'] = int(output['index']) == info['default_output_index']
            choices.append(selection)
        return choices
    except AudioError:
        raise
    except Exception as exc:
        raise AudioError('DEVICE_DISCOVERY_FAILED', str(exc)) from exc
    finally:
        if pa is not None:
            pa.terminate()


def supported_format(pa, module, device, log):
    maximum = int(device.get('maxInputChannels', 0))
    native_rate = int(device.get('defaultSampleRate', 0))
    if maximum < 1 or native_rate < 1:
        raise AudioError('FORMAT_UNSUPPORTED', 'Loopback의 입력 채널 수 또는 샘플레이트가 유효하지 않습니다.')
    channels = list(dict.fromkeys([maximum, min(2, maximum), 1]))
    rates = list(dict.fromkeys([native_rate, 48000, 44100]))
    for rate in rates:
        for count in channels:
            try:
                accepted = pa.is_format_supported(rate, input_device=int(device['index']),
                    input_channels=count, input_format=module.paInt16)
                log.write('format_probe', device_index=device['index'], rate=rate, channels=count, supported=bool(accepted))
                if accepted:
                    return rate, count
            except (ValueError, OSError) as exc:
                log.write('format_probe', device_index=device['index'], rate=rate, channels=count, supported=False, error=str(exc))
    raise AudioError('FORMAT_UNSUPPORTED', 'PCM16의 기본/48000/44100Hz 및 기본/스테레오/모노 조합을 장치가 지원하지 않습니다.')


class TimedPCM:
    """Single writer thread inserts silence for measured gaps without large allocations."""
    def __init__(self, wav, rate, channels):
        self.wav, self.rate, self.channels = wav, rate, channels
        self.frames = 0
        self.padded_frames = 0

    def silence(self, frames):
        while frames > 0:
            n = min(frames, 8192)
            self.wav.writeframesraw(bytes(n*self.channels*2))
            self.frames += n
            self.padded_frames += n
            frames -= n

    def write(self, data, position):
        gap = position - self.frames
        # Below 50ms, prefer the sample clock to callback scheduling jitter.
        if gap > self.rate * 0.05:
            self.silence(gap)
        elif gap < -self.rate * 0.05:
            data = data[min(len(data), -gap*self.channels*2):]
        self.wav.writeframesraw(data)
        self.frames += len(data)//(self.channels*2)


class AudioTrack:
    def __init__(self, path: Path, loopback: bool, selection=None, log=None, module=None):
        self.path = Path(path)
        self.log = log or Diagnostics(self.path.parent/'audio-diagnostics.jsonl')
        self.loopback = loopback
        self.pa_module = module or backend()
        self.pa = None
        self.stream = None
        self.wav = None
        self.writer = None
        self.sink = None
        self.error = None
        self.started = 0.0
        self.received_frames = 0
        self.callback_count = 0
        self.nonzero_packets = 0
        self.last_callback = 0.0
        self.last_nonzero = 0.0
        self.timestamp_fallbacks = 0
        self.timestamp_source = 'monotonic'
        self.status_flags = 0
        self.closed = False
        self.queue = queue.Queue(maxsize=256)
        self.stopping = threading.Event()
        self.ready = threading.Event()
        self.first_adc = None
        self.first_position = None
        self.last_state = None
        self.stop_time = 0.0
        self._commands = queue.Queue()
        self._initialized = Future()
        self._abandoned = threading.Event()
        self._controller = threading.Thread(target=self._control_loop, args=(selection,),
                                            name='MyRecorderWASAPI', daemon=True)
        self._controller.start()
        try:
            self._initialized.result(timeout=15)
        except TimeoutError as exc:
            self._abandoned.set()
            raise AudioError('DEVICE_INIT_TIMEOUT', 'WASAPI 초기화가 15초 안에 완료되지 않았습니다. 로그를 보존하고 장치/드라이버를 확인하세요.') from exc

    def _control_loop(self, selection):
        # WASAPI/COM resources must be initialized, queried, started and released
        # on the same persistent thread, even though GUI jobs use different QThreads.
        try:
            self._open(selection)
        except Exception as exc:
            self._initialized.set_exception(exc)
            return
        if self._abandoned.is_set():
            self._close()
            return
        self._initialized.set_result(None)
        while True:
            command, result = self._commands.get()
            try:
                value = None
                if command == 'start': self._start()
                elif command == 'active': value = self.stream is not None and self.stream.is_active()
                elif command == 'close': self._close()
                result.set_result(value)
            except Exception as exc:
                result.set_exception(exc)
            if command == 'close': return

    def _request(self, command, timeout=15):
        if not self._controller.is_alive():
            raise AudioError('DEVICE_CONTROL_FAILED', 'WASAPI 제어 스레드가 중단되었습니다.')
        result = Future()
        self._commands.put((command, result))
        try:
            return result.result(timeout=timeout)
        except TimeoutError as exc:
            raise AudioError('DEVICE_CONTROL_TIMEOUT', f'WASAPI {command} 요청이 {timeout}초 안에 완료되지 않았습니다.') from exc

    def _open(self, selection):
        try:
            try:
                self.pa = self.pa_module.PyAudio()
            except Exception as exc:
                raise AudioError('DEVICE_DISCOVERY_FAILED', f'PortAudio 초기화 실패: {exc}') from exc
            self.log.write('portaudio', version=self.pa_module.get_portaudio_version_text())
            if self.loopback:
                info = inventory(self.pa, self.pa_module, self.log)
                output, device = select_pair(info, selection)
                self.log.write('selected_pair', output=output, loopback=device)
            else:
                try:
                    device = dict(self.pa.get_default_input_device_info())
                except Exception as exc:
                    raise AudioError('MIC_NOT_FOUND', f'기본 마이크를 찾을 수 없습니다: {exc}') from exc
                self.log.write('selected_microphone', device=device)
            self.device = device
            self.rate, self.channels = supported_format(self.pa, self.pa_module, device, self.log)
            self.wav = wave.open(str(self.path), 'wb')
            self.wav.setnchannels(self.channels)
            self.wav.setsampwidth(2)
            self.wav.setframerate(self.rate)
            self.sink = TimedPCM(self.wav, self.rate, self.channels)
            try:
                self.stream = self.pa.open(format=self.pa_module.paInt16, channels=self.channels, rate=self.rate,
                    input=True, input_device_index=int(device['index']), frames_per_buffer=1024,
                    stream_callback=self.callback, start=False)
            except Exception as exc:
                raise AudioError('DEVICE_OPEN_FAILED', f"'{device['name']}' {self.rate}Hz/{self.channels}ch 열기 실패: {exc}. 장치 사용 중/드라이버/독점 모드를 확인하세요.") from exc
            self.log.write('stream_open', file=self.path.name, input_device_index=int(device['index']),
                           host_api=device['hostApi'], format='PCM16', rate=self.rate, channels=self.channels,
                           input_latency=self.stream.get_input_latency())
        except Exception as exc:
            self.log.write('initialization_failed', file=self.path.name, error=str(exc))
            self._close()
            raise

    @property
    def frames(self):
        return self.sink.frames if self.sink else 0

    def callback(self, data, count, timing, status):
        # No disk I/O or logger in PortAudio's real-time callback.
        try:
            self.callback_count += 1
            self.status_flags |= int(status)
            now = time.monotonic()
            self.last_callback = now
            if data:
                if len(data) % (self.channels*2):
                    raise AudioError('INVALID_PCM', 'PCM 데이터가 채널 프레임 경계에 맞지 않습니다.')
                actual = len(data)//(self.channels*2)
                self.received_frames += actual
                nonzero = any(data)
                self.nonzero_packets += int(nonzero)
                if nonzero: self.last_nonzero = now
                adc = float((timing or {}).get('input_buffer_adc_time', 0) or 0)
                if not math.isfinite(adc): adc = 0
                monotonic_position = max(0, round((now-self.started)*self.rate)-actual)
                current = float((timing or {}).get('current_time', 0) or 0)
                measured_position = monotonic_position
                if adc > 0 and math.isfinite(current) and current > 0 and 0 <= current-adc < 5:
                    measured_position = max(0, round((now-self.started+adc-current)*self.rate))
                    self.timestamp_source = 'adc-current_time'
                if self.first_position is None:
                    self.first_position = measured_position
                    self.first_adc = adc if adc > 0 else None
                if self.first_adc is not None and adc >= self.first_adc:
                    position = self.first_position + round((adc-self.first_adc)*self.rate)
                else:
                    position = monotonic_position
                if abs(position-monotonic_position) > self.rate:
                    position = monotonic_position
                    self.timestamp_fallbacks += 1
                self.queue.put_nowait((data, position))
                self.ready.set()
            return (None, self.pa_module.paContinue)
        except queue.Full:
            self.error = self.error or '[BUFFER_OVERFLOW] 오디오 파일 쓰기가 수신 속도를 따라가지 못했습니다. 임시 파일을 보존하세요.'
        except Exception as exc:
            self.error = self.error or str(exc)
        self.ready.set()
        return (None, self.pa_module.paAbort)

    def _write(self):
        try:
            while not self.stopping.is_set() or not self.queue.empty():
                try:
                    data, position = self.queue.get(timeout=0.1)
                except queue.Empty:
                    # Keep long no-packet intervals on disk progressively. Leave a
                    # 500ms holdback so normal callback latency does not erase PCM.
                    if self.started:
                        target = max(0, round((time.monotonic()-self.started-0.5)*self.rate))
                        self.sink.silence(max(0, target-self.sink.frames))
                    continue
                self.sink.write(data, position)
            if self.started and self.stop_time:
                target = max(0, round((self.stop_time-self.started)*self.rate))
                self.sink.silence(max(0, target-self.sink.frames))
        except Exception as exc:
            self.error = f'[AUDIO_WRITE_FAILED] {exc}'
        finally:
            try:
                self.wav.close()
            except Exception as exc:
                self.error = self.error or f'[AUDIO_WRITE_FAILED] WAV 종료 실패: {exc}'

    def start(self):
        return self._request('start')

    def _start(self):
        self.started = time.monotonic()
        self.writer = threading.Thread(target=self._write, name='MyRecorderPCM', daemon=True)
        self.writer.start()
        try:
            self.stream.start_stream()
        except Exception as exc:
            raise AudioError('DEVICE_START_FAILED', f'오디오 스트림 시작 실패: {exc}') from exc
        self.log.write('stream_started', file=self.path.name, monotonic=self.started)

    def wait_ready(self, timeout=1.0):
        self.ready.wait(timeout)
        state = self.snapshot()
        if state['state'] == 'ERROR':
            raise AudioError('CAPTURE_FAILED', state['detail'])
        return state

    def _active(self):
        try:
            return self._request('active', timeout=2)
        except Exception as exc:
            self.error = f'[STREAM_STATUS_FAILED] {exc}'
            return False

    def snapshot(self, now=None):
        now = time.monotonic() if now is None else now
        elapsed = max(0, now-self.started) if self.started else 0
        detail = ''
        if self.error or self.log.error:
            state, detail = 'ERROR', self.error or ('[DIAGNOSTICS_WRITE_FAILED] ' + self.log.error)
        elif self.started and not self.closed and not self._active():
            state, detail = 'ERROR', self.error or '[STREAM_STOPPED] 오디오 장치가 중단되었습니다. 연결과 기본 장치를 확인하세요.'
        elif not self.received_frames:
            if elapsed < STARTUP_GRACE:
                state, detail = 'WAITING', '오디오 초기화/첫 데이터 수신 대기 중입니다. 선택한 출력 장치로 소리를 재생하세요.'
            else:
                state, detail = 'NO_DATA_TIMEOUT', '8초 이상 오디오 데이터가 없습니다. 무음·재생 장치 불일치·드라이버 지연 중 원인을 단정할 수 없습니다. 선택 장치에서 소리를 재생해 확인하세요.'
        elif self.status_flags:
            state, detail = 'BUFFER_WARNING', f'PortAudio 버퍼 상태 플래그 {self.status_flags}: 음성 일부 누락 가능. 로그를 확인하세요.'
        elif now-self.last_callback > STARTUP_GRACE and not self.closed:
            state, detail = 'NO_DATA_TIMEOUT', '수신 도중 8초 이상 데이터가 없습니다. 무음인지 장치 중단인지 확인하세요.'
        elif self.nonzero_packets == 0 or now-self.last_nonzero > 1.0:
            state, detail = 'SILENT', 'PCM 데이터는 수신되었지만 최근 데이터는 디지털 무음입니다. Windows 볼륨과 앱 출력을 확인하세요.'
        else:
            state, detail = 'RECEIVING', '오디오 데이터를 수신하고 있습니다.'
        result = {'state': state, 'detail': detail, 'file': self.path.name, 'callbacks': self.callback_count,
                  'received_frames': self.received_frames, 'written_frames': self.frames,
                  'padded_frames': self.sink.padded_frames if self.sink else 0,
                  'nonzero_packets': self.nonzero_packets, 'status_flags': self.status_flags,
                  'timestamp_fallbacks': self.timestamp_fallbacks, 'timestamp_source': self.timestamp_source}
        if state != self.last_state:
            self.log.write('capture_state', **result)
            self.last_state = state
        return result

    def close(self):
        if self.closed:
            return
        try:
            self._request('close')
        except Exception as exc:
            self.error = self.error or f'[AUDIO_CLOSE_FAILED] {exc}'
            self.log.write('close_failed', file=self.path.name, error=self.error)

    def _close(self):
        if self.closed:
            return
        self.closed = True
        self.stop_time = time.monotonic()
        errors = []
        if self.stream is not None:
            try:
                if self.stream.is_active(): self.stream.stop_stream()
            except Exception as exc:
                errors.append(str(exc))
            try:
                self.stream.close()
            except Exception as exc:
                errors.append(str(exc))
            self.stream = None
        self.stopping.set()
        if self.writer is not None:
            self.writer.join(timeout=10)
            if self.writer.is_alive():
                errors.append('PCM 파일 쓰기 종료 시간 초과. 파일을 보존하세요.')
        elif self.wav is not None:
            try:
                self.wav.close()
            except Exception as exc:
                errors.append(str(exc))
        if self.pa is not None:
            try:
                self.pa.terminate()
            except Exception as exc:
                errors.append(str(exc))
            self.pa = None
        if errors:
            self.error = '[AUDIO_CLOSE_FAILED] ' + '; '.join(errors)
        self.log.write('stream_closed', file=self.path.name, received_frames=self.received_frames,
                       written_frames=self.frames, error=self.error, cleanup_errors=errors)


def main():
    """Windows diagnosis without GUI; all files stay in the configured Temp folder."""
    import argparse
    import uuid
    from .settings import SettingsStore, storage_directory
    parser = argparse.ArgumentParser(description='MyRecorder Windows WASAPI 진단')
    parser.add_argument('--seconds', type=float, default=0, help='시스템 소리 시험 녹음 시간 (0: 목록만)')
    parser.add_argument('--output-device-id', type=int, help='목록의 WASAPI 출력 ID, 생략하면 기본 출력')
    args = parser.parse_args()
    if not 0 <= args.seconds <= 300:
        parser.error('--seconds는 0~300이어야 합니다.')
    folder = storage_directory(SettingsStore().load().temp)/('audio-test-'+uuid.uuid4().hex)
    folder.mkdir()
    log = Diagnostics(folder/'audio-diagnostics.jsonl')
    track = None
    try:
        choices = device_choices(log)
        print(json.dumps(choices, ensure_ascii=False, indent=2))
        print(f'진단 로그: {log.path}', flush=True)
        if args.seconds:
            selection = None
            if args.output_device_id is not None:
                selection = next((c for c in choices if c['index'] == args.output_device_id), None)
                if selection is None:
                    raise AudioError('OUTPUT_NOT_FOUND', '지정한 출력 ID가 없습니다.')
            print('선택한 출력 장치에서 소리를 재생하세요.', flush=True)
            track = AudioTrack(folder/'system.wav', True, selection=selection, log=log)
            track.start()
            deadline = time.monotonic()+args.seconds
            while time.monotonic() < deadline:
                state = track.snapshot()
                print(json.dumps(state, ensure_ascii=False), flush=True)
                if state['state'] == 'ERROR':
                    raise AudioError('CAPTURE_FAILED', state['detail'])
                time.sleep(min(1.0, max(0, deadline-time.monotonic())))
            state = track.snapshot()
            track.close()
            print(f'시험 WAV: {track.path}')
            if state['state'] == 'ERROR' or track.error:
                raise AudioError('CAPTURE_FAILED', track.error or state['detail'])
            if not track.received_frames or not track.nonzero_packets:
                print('실제 소리 수신이 확인되지 않았습니다. 상태와 로그를 확인하세요.')
                return 2
            print('비영(非零) PCM 수신. WAV를 재생해 실제 소리와 품질을 확인하세요.')
        return 0
    except Exception as exc:
        log.write('diagnosis_failed', error=str(exc))
        print(f'{exc}\n로그: {log.path}')
        return 1
    finally:
        if track is not None: track.close()


if __name__ == '__main__':
    raise SystemExit(main())
