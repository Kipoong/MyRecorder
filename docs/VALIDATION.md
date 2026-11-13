# 버전별 검증 이력

| 버전·출처 | 환경 | 결과 | 범위와 한계 |
|---|---|---|---|
| V0.2 사용자 보고 | Windows 11 | GUI·무음 화면·MP4 성공, 시스템 소리 미수신 오류 | 당시 결과이며 V0.3 이후 상태와 구분 |
| V0.3 사용자 보고 | Windows 11 | **기본 기능 테스트 통과** | 화면 녹화, WASAPI 시스템 오디오 녹음, F드라이브 MP4 저장 모두 정상 |
| V0.3 개발 검사 | Linux | 자동 테스트 38개·Qt offscreen 통과 | 모의 오디오·합성 미디어; Windows 실기 대체 아님 |
| V0.4 개발 검사 | Linux | 자동 테스트 73개·Qt offscreen 통과 | 기존 테스트 유지, 제목/OCR 호출·DPI 수학·정리 보호·시간 검사 추가 |
| V0.4 OCR 도구 시험 | Linux/Tesseract 5.5.0 | 합성 영어 제목 실제 인식 통과 | 메모리 PNG → stdin → OCR stdout. Windows 화면 캡처·한국어 인식은 아님 |
| V0.4 새 기능 실기 | Windows 11 | **검증 대기** | 창 제목·한국어 OCR·100/125/150% 좌표·일시정지 싱크·장시간·정리 UI·EXE |
| V0.4.1 개발 검사 | Linux | 자동 테스트 88개·기존/신규 Qt smoke 통과 | 영역 편집·색상 렌더링·상태·모의 제외 API/실패 숨김. 네이티브 입력/제외 아님 |
| V0.4.1 사용자 보고 | Windows 11 듀얼 100% | **녹화 시작 실패** | 영역 선택·초록 테두리·이동은 성공, Qt/Windows 모니터 대응 오류. 앞선 단일 모니터 조건 정정 |
| V0.4.2 개발 검사 | Linux | 자동 테스트 105개·Qt smoke 통과 | 합성 듀얼 목록 역순·음수 원점·100/125/150%·DPI 초기화 모의·시작 차단·로그 검사 |
| V0.4.2 실기 | Windows 11 | **검증 대기** | 네이티브 모니터 조회·DPI 경고·듀얼 전체/부분·혼합 배율·오디오/MP4 회귀 |

사용자 실기 결과는 사용자가 확인한 항목만 기록합니다. V0.3 기본 기능 통과를 다른 장치,
긴 녹화, 모든 배율, 마이크 동시 녹음 또는 V0.4 신규 기능까지 확대 해석하지 않습니다.
Windows의 실제 기기명·계정 경로·개인 진단 로그는 이 공개 문서에 포함하지 않습니다.

## V0.4 개발 환경에서 실제 실행한 검사

```sh
python -m compileall -q myrecorder tests launcher.py
python -m unittest discover -s tests -v
QT_QPA_PLATFORM=offscreen PYTHONPATH=. python tests/gui_smoke.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=. python tests/ocr_smoke.py
```

Qt smoke는 PySide6를 설치한 별도 가상환경 Python으로 실행했습니다.
Fontconfig 캐시/offscreen 창 표시 관련 경고가 있었지만 검사는 통과했습니다.
자동 테스트에서는 Windows API와 오디오 장치 일부를 모의 처리하며 실제 Windows 작업을 실행하지 않습니다.
실제 합성 MP4는 FFmpeg로 생성·결합·변환·디코딩했고, 영어 OCR은 실제 Tesseract를 호출했습니다.
기존 WASAPI 구현 파일은 V0.3과 동일하고 FFmpeg 캡처·인코딩 인자도 유지했습니다.

실기 기록 양식과 판정 기준은 [WINDOWS_V0.4.md](WINDOWS_V0.4.md)에 있습니다.

V0.4.1 점검 결과와 제한은 [REGION_OVERLAY_V0.4.1.md](REGION_OVERLAY_V0.4.1.md)를 참고하세요.
Qt offscreen의 마스크·마우스 캡처·창 올리기 미지원 경고가 있어 네이티브 동작 통과로 취급하지 않습니다.

V0.4.2 추가 실행: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen python tests/display_smoke.py`와
기존 GUI/overlay/OCR smoke. 새 검사와 실기표: [DISPLAY_V0.4.2.md](DISPLAY_V0.4.2.md).

## V0.4.3

Linux 자동 테스트 113개 통과, 기존 GUI/overlay/display/OCR 및 신규 continuous smoke 통과.
합성 미디어 세 번 저장/디코딩과 이전 파일 해시 보존을 확인했습니다.
실제 Windows 연속 녹화/듀얼 모니터 드래그/드라이버 종료/영상 제외/싱크는 미검증입니다.
[검증 범위 및 재검증표](CONTINUOUS_V0.4.3.md).

## V0.5.0

Linux unittest 127개와 GUI/overlay/display/continuous/modes_desktop/OCR smoke 통과.
합성 6구간(5회 정지 모델) MP4 결합, PTS/DTS 및 경계 시험음을 검사했습니다.
Windows 실제 모드 사용/다중 화면 캡처/혼합 DPI/싱크/영상 제외/복구/EXE는 미검증입니다.
[시험 범위와 Windows 절차](MODES_DESKTOP_V0.5.md).

## V0.6.0 개발 직전 사용자 실기 보고

Windows 11 모니터 1에서 화면 녹화, 시스템 오디오, MP4 저장과 실제 영상·음성 싱크 정상 확인.
사용자가 명시한 범위만 기록하며 다른 모니터/자동 연동까지 통과로 확대하지 않습니다.

## V0.6.0

Linux unittest 143개 및 기존/신규 Qt smoke 통과. 실제 Chromium 압축해제 확장과 HTML5/로컬
HTTP에서 5회 ready 게이트/정지·다른 탭·버퍼링·관찰 우회·끊김 검사를 수행했습니다.
Qt/브라우저 녹화 엔진은 모의이며 Windows 자동 캡처·오디오·싱크 통과가 아닙니다.
[시험 범위·한계와 Windows 절차](AUTO_LINK_V0.6.md).
