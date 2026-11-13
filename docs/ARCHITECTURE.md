# 구조와 기술적 위험

## 프로젝트

```
myrecorder/
  settings.py    개발 폴더 settings.json, 세 저장 위치 검증·생성·OneDrive 차단
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

GUI → 작업 스레드 → 오디오 장치 준비 → FFmpeg gdigrab 시작 → PCM 콜백 기록.
일시정지 → 장치 정지/WAV 헤더 완료 → FFmpeg q 종료 → 메타데이터 저장.
재개 → 동일 옵션의 새 구간. 저장 → 오디오 지연 보정/믹싱 → AAC MP4 구간 → concat →
ffprobe 검사 → 최종 파일명 예약 → 같은 파일시스템에서 원자적 교체.

오디오는 16bit PCM, 최대 2채널이며 원래 장치 샘플레이트를 사용.
2개 장치 혼합은 amix normalize=1로 클리핑을 줄이지만 레벨이 낮아질 수 있음.
빈 녹음과 버퍼 오류는 사용자에게 알림. 오디오 콜백 파일 I/O가 느리면 버퍼 오류 가능.
장치 분리·변경 시 자동 복구나 다른 장치로 전환하는 기능은 없음.

## 싱크 제한

영상 FFmpeg 프로세스 생성 시각과 첫 오디오 콜백 시각 차이를 기록하고 adelay 적용.
이는 영상의 실제 첫 프레임 시각과 정확히 같지 않아 초기 싱크 오차가 있을 수 있음.
각 장치의 PCM 샘플 수와 영상 타임스탬프는 독립된 시계를 사용.
aresample=async=1만으로 장치 간 장시간 시계 드리프트가 해결된다고 주장하지 않음.
정밀 싱크에는 공통 시계 타임스탬프 수집·보정 또는 통합 캡처 백엔드가 필요.
현재 일시정지 경계에는 장치 준비 시간과 인코더 초기화에 따른 짧은 공백·단절이 가능.
최종 MP4 길이를 맞추기 위해 오디오는 무음 패딩 후 영상 길이에 맞춰 종료.

## 운영 제한

모든 모니터 100% 배율을 MVP 전제로 하고 Qt devicePixelRatio 검사로 제한.
다중 모니터 음수 좌표와 다양한 GPU/배율은 Windows 실기에서 확인해야 함.
앱 창·알림·테두리는 제외 캡처를 보장하지 않음. 한 모니터 내 영역만 선택.
타이머는 경과 시각으로 실제 미디어 길이와 약간 다를 수 있음.
저장 작업에 취소 UI·자동 디스크 용량 모니터·자동 임시 파일 정리 없음.
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
