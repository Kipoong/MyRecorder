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
| V0.4.1 실기 | Windows 11 | **검증 대기** | 상시 테두리·DPI·실제 입력 통과·gdigrab 영상 제외·기본 녹화 회귀 |

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
