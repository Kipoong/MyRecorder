# 구조와 기술적 위험

## 프로젝트

```
myrecorder/
  settings.py    개발 폴더 settings.json, 세 저장 위치 검증·생성·OneDrive 차단
  titles.py      Win32 창 제목 / 수동 Tesseract OCR (선택 설치)
  display.py     Qt 논리 영역 → 모니터별 Win32 물리 좌표 / 메모리 OCR 이미지
  maintenance.py 검증된 완료 세션의 명시적 정리
  regions.py     모니터 내 이동·8방향 크기 조절의 순수 좌표 계산
  window_capture.py 자체 최상위 창의 WDA_EXCLUDEFROMCAPTURE 설정·읽기 확인
  overlay.py     상시 테두리·상태색·픽셀 라벨·비어 있는 가운데·입력 잠금
  gui.py         PySide6 GUI, 영역 선택, 작업 스레드
  recorder.py    Windows gdigrab 구간 녹화, 세션 메타데이터
  audio.py       PyAudioWPatch WASAPI loopback / 기본 입력 PCM
  media.py       FFmpeg 실행, 믹싱·결합·검증·파일명·실험용 변환
  cli.py         제한적 복구 / 실험용 배속 변환
  __main__.py    GUI 진입점
bin/             사용자가 FFmpeg와 ffprobe 배치
install.bat      Python 3.12 가상환경 및 패키지 설치
run.bat          GUI 실행
build.bat        Windows에서 PyInstaller onedir EXE 빌드
launcher.py      EXE 진입점
tests/           Linux에서도 가능한 합성 미디어·저장 로직 테스트
docs/            구조 및 Windows 검증 절차
```

## 선택 근거

- PySide6: 한국어 GUI·영역 오버레이. LGPL/GPL/상용 라이선스 조건 확인 필요.
- FFmpeg gdigrab: Windows 데스크톱과 커서 캡처가 가능한 기존 구현.
  CPU 인코딩은 4K/60 FPS에서 부담이 큼. 기본값 30 FPS / ultrafast x264.
  GPL 기능을 포함한 FFmpeg 빌드는 해당 라이선스 조건을 따름.
- PyAudioWPatch: 일반 PyAudio와 달리 Windows WASAPI 출력 루프백 장치를 제공.
  Stereo Mix 장치가 없어도 기본 출력 장치의 소리를 캡처할 수 있는 구조.
- MKV 구간 + WAV: 최종 MP4 헤더가 쓰이기 전에 앱이 종료되는 문제를 줄임.
  완전한 크래시 내구성이나 정전 복구를 보장하지 않음.
- OCR·창 제목 읽기는 Windows API/OCR 의존성과 제목 오인식 가능성이 있어 후속 단계.

## 녹화 흐름

GUI → 작업 스레드 → 오디오 장치 준비 → FFmpeg gdigrab 시작 → PCM 콜백 → 유한 큐 → 쓰기 스레드의 타임스탬프 기반 기록.
일시정지 → 장치 정지/WAV 헤더 완료 → FFmpeg q 종료 → 메타데이터 저장.
재개 → 동일 옵션의 새 구간. 저장 → 오디오 지연 보정/믹싱 → AAC MP4 구간 → concat →
ffprobe 검사 → 최종 파일명 예약 → 같은 파일시스템에서 원자적 교체.

오디오는 PCM16이며 장치의 원래 채널/샘플레이트를 우선 검사하고, 필요하면 2채널/모노 및 48000/44100Hz로 대체.
2개 장치 혼합은 amix normalize=1로 클리핑을 줄이지만 레벨이 낮아질 수 있음.
미수신·무음·버퍼 오류를 구분해 안내. 콜백은 디스크 I/O 없이 유한 큐에 넣으며, 쓰기가 느려 큐를 넘으면 명시적 오류.
장치 분리·변경 시 자동 복구나 다른 장치로 전환하는 기능은 없음.

## 싱크 제한

영상 FFmpeg 프로세스 생성 시각과 오디오 스트림 시작 시각 차이를 기록하고 adelay 적용.
첫 PCM은 유효한 PortAudio ADC/current 시각으로 콜백 지연을 보정하고 이후 ADC 간격을 사용.
타임스탬프가 없거나 크게 불안정하면 단조 시각으로 대체. 수신 공백을 무음 패딩으로 유지.
이는 영상의 실제 첫 프레임 시각과 정확히 같지 않아 초기 싱크 오차가 있을 수 있음.
각 장치의 PCM 샘플 수와 영상 타임스탬프는 독립된 시계를 사용.
aresample=async=1만으로 장치 간 장시간 시계 드리프트가 해결된다고 주장하지 않음.
정밀 싱크에는 공통 시계 타임스탬프 수집·보정 또는 통합 캡처 백엔드가 필요.
현재 일시정지 경계에는 장치 준비 시간과 인코더 초기화에 따른 짧은 공백·단절이 가능.
최종 MP4 길이를 맞추기 위해 오디오는 무음 패딩 후 영상 길이에 맞춰 종료.

## 운영 제한

V0.4는 Qt 6의 기본 모니터별 DPI 인식을 사용하고 선택 영역을 물리 좌표로 변환.
100/125/150% 수학 검사는 통과했지만 Windows에서 각 배율의 실기 확인은 대기.
화면 대응/인식 모드가 불확실하면 경고하고 시작을 차단.
다중 모니터 음수 좌표와 다양한 GPU/배율은 Windows 실기에서 확인해야 함.
앱 창·알림·테두리는 제외 캡처를 보장하지 않음. 한 모니터 내 영역만 선택.
실시간 타이머는 추정이며 닫힌 구간은 ffprobe 길이로 보정하고 저장 후 최종 영상 길이를 표시.
저장 취소 UI·자동 디스크 모니터·자동 정리 스케줄은 없음. V0.4는 정상 완료 세션 수동 정리 UI 제공.
GUI 오류 후 프로세스가 살아 있으면 종료 버튼으로 재시도할 수 있음.
구간이 손상되어 계속 저장 실패하면 임시 폴더를 보존하고 작업 관리자로 종료.

DRM·HDCP·보호된 창은 검은 화면 또는 무음일 수 있음. 우회하지 않음.

## 0.2 저장 경로 변경

기본 Recordings/Converted/Temp는 F:\MyRecorder 아래 서로 다른 폴더.
세 경로는 settings.py의 StoragePaths로 전달하고 GUI SettingsDialog에서 검증 후 저장.
설정 파일은 개발 폴더 settings.json에 UTF-8 JSON으로 원자적 갱신. QSettings는 제거.
드라이브 누락·쓰기 실패·상대경로·OneDrive·개발 폴더를 거부하며 대체 폴더를 자동 선택하지 않음.
녹화 엔진은 GUI 외 직접 호출 시에도 prepare_storage를 사용해 방어.
세션 메타데이터에 원래 저장·변환·임시 폴더와 title_source를 기록.
배속 CLI도 설정의 Converted와 Temp를 사용. 복구 CLI는 명시된 저장 폴더를 검증.
최종 인코딩 임시 파일은 Temp에서 만들고 동일 볼륨은 os.replace로 게시.
다른 볼륨은 대상 .partial에 복사·fsync 후 replace. 강제 종료 시 .partial/예약 MP4 잔류 가능.
출력 드라이브가 중간에 사라지면 오류를 표시하고 세션을 보존하며 자동 경로 변경은 하지 않음.

Windows 전체 경로 길이 제한은 Python·FFmpeg·Windows 설정에 따라 여전히 있을 수 있음.
매우 긴 폴더 대신 짧은 미디어 경로를 권장. 배치의 한글·공백 경로 인수는 인용했으나
Windows 실기 검증을 대체하지 않음.

## V0.3 오디오 생명주기와 오류 처리

WASAPI/COM 관련 PyAudio 생성·장치 열기·start·is_active·stop·terminate는
각 트랙의 같은 전용 제어 스레드에서 수행. GUI의 start/pause 작업 QThread가 달라도
네이티브 리소스의 생성/종료 스레드를 바꾸지 않음. 콜백은 별도 PortAudio 스레드이며
파일 기록은 PCM 쓰기 스레드. 제어 요청은 Future로 결과/예외를 전달하고 시간 제한을 둠.
실제 드라이버가 네이티브 호출에서 멈추면 Python만으로 강제 취소할 수는 없음.

시작 중 실패한 구간은 session.json에 usable=false와 startup_error를 기록.
다음 정상 구간과 기존 구간을 합칠 때 실패한 시작 구간을 건너뛰되 파일은 보존.
일시정지 후 finish의 중복 pause는 이전 트랙 메타데이터를 지우지 않음.
미수신 중에도 영상 녹화를 유지하고 상태 경고, 종료 시 실제 수신 프레임이 0이면 경고.
무음 패딩 프레임과 실제 수신 프레임은 별도 계수하여 패딩을 수신 성공으로 오인하지 않음.
장치 선택은 현재 GUI 세션 동안 유지되며 디스크 설정 스키마·기존 미디어 경로는 불변.
상세 한계·로그·Windows 테스트는 WINDOWS_AUDIO_V0.3.md 참고.

## V0.4 독립 기능과 원본 보호

V0.3 audio.py는 변경하지 않음. FFmpeg의 gdigrab, x264, 커서·FPS·패딩 인자는 유지.
GUI에서 선택한 DIP 영역만 display.physical_region으로 모니터별 물리 좌표에 대응.
구형 SetProcessDPIAware를 제거하고 EXE에 windows.manifest를 사용.

제목 인식은 대기 상태에서만 실행. 창 제목 Win32 API는 제목 문자열만 읽으며 브라우저 내부에
접근하지 않음. OCR 선택 영역은 GUI 스레드에서 PNG로 만들고 메모리 stdin으로 Tesseract에 전달.
OCR subprocess는 작업 스레드에서 실행하고 언어·실행 시간·오류를 검사.
실패 시 기존 입력 유지, 인식 결과는 normalize_title → safe_title을 거쳐 사용자에게 표시.
사용자 수정은 title_source를 manual로 바꾸고 세션에 출처를 기록. 설정 스키마는 유지.

세션 매니페스트 version=3, owner=MyRecorder, status를 기록. 기존 복구/결합은 이전 버전과 호환.
추가 recording-events.jsonl에 구간 경계·물리 영역·저장 오류 기록. 일시정지 후 영상 구간 길이,
저장 후 최종 비디오/오디오 길이와 구간 합계를 확인. 이는 실제 음성 내용 싱크 검사는 아님.

정리는 사용자가 요청한 경우에만 수행. saved 표식, 모든 구간 complete, 실제 최종 MP4의
경로/크기/probe를 확인하고 삭제 직전에 재검사. 세션 내부 링크/정션, 세션 안 최종 MP4,
불완전 구간이나 과거 버전 세션은 거부. raw 원본은 기본적으로 보관하며 실패 시 자동 삭제하지 않음.
상세 설명과 검증 구분은 WINDOWS_V0.4.md, VALIDATION.md 참고.

## V0.4.1 영역 오버레이

recorder/audio/media/display/settings와 캡처/오디오 인자는 V0.4 그대로 유지.
GUI 선택 영역을 별도 RegionOverlay로 표시하고 idle일 때만 편집 신호를 GUI에 반영.
녹화 전 입력 통과 플래그와 제외 속성을 준비하고 핸들이 바뀌면 다시 확인.
실제 캡처 중(시작/재개/저장 종료 경계 포함) 제외 미확인이면 표시하지 않음.
OS API 성공은 실제 gdigrab 제외 시험을 대신하지 않음. 네이티브 Windows 검증 대기.
자세한 소스 판정과 사용법은 REGION_OVERLAY_V0.4.1.md 참고.

## V0.4.2 디스플레이 경계

`dpi_bootstrap.py`가 Qt 가져오기 전에 한 번 DPI 정책을 설정합니다.
`winmon.py`는 Win32 물리 모드·모니터 식별/DPI를 수집하고 `display.py`는 Qt 화면과
검증된 고유 대응을 구성합니다. `coordinate_log.py`는 설정 Temp에만 JSONL을 씁니다.
GUI는 선택한 QScreen 객체와 선택 시 이름/좌표/DPR을 유지하고 녹화 시작 직전 재검증합니다.
오류 발생 시 Recorder 생성 전에 중단합니다. 기존 녹화·오디오·저장 모듈은 그대로입니다.
