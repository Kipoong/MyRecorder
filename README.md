# MyRecorder 0.2 — Windows 11 우선 MVP

개인용 화면·시스템 소리·마이크 녹화 프로그램입니다. 기존 녹화 기능을 유지하면서
저장 경로를 녹화 / 변환 / 임시 폴더로 분리했습니다.
**Windows에서 실제 화면·음성 녹화와 BAT·EXE 실행은 아직 검증하지 않았습니다.**
DRM·HDCP 등 콘텐츠 보호 기술을 우회하지 않습니다.

## GitHub에서 Windows PC로 다운로드

1. https://github.com/Kipoong/MyRecorder 저장소에서 **Code → Download ZIP**을 선택합니다.
2. 내려받은 ZIP을 임의의 작업 폴더에 압축 해제합니다. GitHub가 생성한 최상위 폴더는
   보통 `MyRecorder-main`입니다. 이 폴더의 이름을 `myrecorder`로 바꿉니다.
3. 폴더 전체를 `%USERPROFILE%\OneDrive\바탕 화면\allthetest`로 옮깁니다.
   `myrecorder\install.bat`이 바로 있어야 합니다. 그 안의 `myrecorder\gui.py` 패키지는 정상입니다.
4. 아래의 Python 3.12 x64와 FFmpeg 준비를 마친 뒤 `install.bat` → `run.bat` 순서로 실행합니다.
   ZIP에는 개인 `settings.json`, 인증 정보, 영상, 가상환경, 빌드 산출물이 없습니다.

공개 문서에서는 사용자 계정명 대신 `%USERPROFILE%` 예시를 사용합니다.
기존 사용자 설정은 Git에 올리지 않으며, 앱의 최초 실행이 개발 폴더에 생성합니다.

## 확정된 폴더 구조

| 용도 | 기본 위치 |
|---|---|
| 개발·실행·설정·배치 파일 | `%USERPROFILE%\OneDrive\바탕 화면\allthetest\myrecorder` |
| 최종 녹화 MP4 | `F:\MyRecorder\Recordings` |
| 변환 결과 MP4 | `F:\MyRecorder\Converted` |
| 녹화 구간·PCM 음성·중간 영상·복구 로그 | `F:\MyRecorder\Temp\session-임의ID` |

개발 경로를 코드에 하드코딩하지 않습니다. 배치 파일은 자신의 위치를 기준으로 실행합니다.
소스 실행은 프로젝트 루트, EXE는 프로젝트 표식 `myrecorder.project.json`이 있는 상위
폴더를 찾아 `settings.json`을 사용합니다. `run.bat`은 `MYRECORDER_HOME`도 지정합니다.
따라서 위 한글·공백 경로에 두어도 상대 작업 디렉터리에 의존하지 않습니다.

## 기존 배포 ZIP 압축 해제 및 첫 실행

GitHub ZIP을 사용했다면 위 절차로 폴더를 옮긴 뒤 아래 **4번부터** 진행하세요.
다음 1~3번은 `MyRecorder-0.2-Windows-Paths.zip` 원본 배포 ZIP을 별도로 전달받았을 때의 절차입니다.

1. 원본 배포 ZIP을 Windows PC로 내려받습니다. ZIP 안에는 `myrecorder` 폴더 하나가 있습니다.
2. ZIP을 우클릭 → **모두 압축 풀기** → 대상 폴더를
   `%USERPROFILE%\OneDrive\바탕 화면\allthetest`로 지정합니다.
   최종적으로 아래 파일이 있어야 합니다. 중복 `myrecorder\myrecorder\install.bat`이
   생기지 않도록 확인하세요. 내부의 `myrecorder` Python 패키지 하위 폴더는 정상입니다.

   ```text
   %USERPROFILE%\OneDrive\바탕 화면\allthetest\myrecorder\install.bat
   %USERPROFILE%\OneDrive\바탕 화면\allthetest\myrecorder\run.bat
   %USERPROFILE%\OneDrive\바탕 화면\allthetest\myrecorder\myrecorder\gui.py
   ```

3. 기존 버전이 있다면 먼저 백업하세요. ZIP에는 실제 `settings.json`이 들어 있지 않아
   기존 사용자 설정을 덮어쓰지 않습니다. 새 버전 첫 실행은 과거 QSettings/레지스트리의
   저장 경로를 가져오지 않고, `settings.json`이 없으면 F드라이브 기본값으로 시작합니다.
4. Python 공식 사이트 https://www.python.org/downloads/windows/ 에서
   **Python 3.12 x64**를 Python Launcher(`py`)와 함께 설치합니다.
5. FFmpeg 공식 페이지 https://ffmpeg.org/download.html#build-windows 에서
   `gdigrab`, `libx264`, AAC를 포함한 Windows 빌드를 선택합니다.
   `ffmpeg.exe`와 `ffprobe.exe`를 프로젝트의 `bin` 폴더에 복사하세요.
   ZIP에는 FFmpeg 실행 파일이 포함되어 있지 않습니다.
6. `install.bat`을 더블클릭합니다. 프로젝트의 `.venv`에 패키지를 설치합니다.
   인터넷 연결이 필요합니다. 관리자 권한은 보통 필요하지 않습니다.
7. `run.bat`을 실행합니다. 최초 실행 시 개발 폴더에 `settings.json`을 만들고,
   접근 가능한 세 미디어 폴더를 자동 생성하고 쓰기 가능 여부를 검사합니다.
8. F드라이브가 없거나 쓰기가 안 되면 경고와 **저장 경로 설정** 화면이 열립니다.
   **C드라이브나 개발 폴더로 자동 대체하지 않습니다.** 세 경로를 모두 접근 가능한
   다른 폴더로 지정하세요. 취소하면 녹화할 수 없고, 다음 시작 시 다시 검사합니다.
9. 모든 모니터의 Windows 디스플레이 배율을 **100%**로 설정한 뒤 앱을 재실행하세요.
   혼합 DPI/125% 이상 배율은 현재 MVP에서 차단합니다.

명령줄을 사용한다면 CMD에서:

```bat
cd /d "%USERPROFILE%\OneDrive\바탕 화면\allthetest\myrecorder"
install.bat
run.bat
```

## 저장 경로 설정

메인 화면의 **저장 경로 설정**을 누르면 녹화·변환·임시 폴더를 각각 입력하거나
찾아보기로 고를 수 있습니다. 저장 시 폴더를 생성하고 실제 쓰기 검사를 거친 뒤
`settings.json`에 원자적으로 저장합니다. 앱 종료 후에도 유지됩니다.
녹화 중에는 경로 변경이 잠깁니다. 녹화 시작 직전에도 재검사합니다.
세 폴더는 서로 달라야 하며 일반 절대 경로나 UNC 공유 경로를 사용하세요.
사용자가 명시적으로 고른 C드라이브의 일반 폴더는 허용하지만, 자동 선택은 없습니다.

**영상 및 임시 파일은 개발 폴더와 OneDrive 경로 안에 저장할 수 없습니다.**
경로 구성요소와 해석된 경로, Windows의 OneDrive 환경 변수로 검사합니다.
추가 동기화 도구·임의 사용자 지정 동기화 루트까지 자동 탐지하는 것은 보장하지 않습니다.
설정·소스·`.venv`·EXE 빌드 산출물은 개발 폴더에 있으므로 OneDrive 동기화 대상일 수 있습니다.

예시 설정은 `settings.example.json`입니다. 실제 `settings.json`은 최초 실행 시 생성됩니다.
설정이 손상되면 자동 초기화하지 않고 오류를 표시합니다. 기존 설정을 백업하고 예시를
참고해 수정하세요. 개발 폴더가 읽기 전용이면 설정을 저장할 수 없다는 오류가 표시됩니다.

## 30초 녹화 시험

1. Windows 기본 소리 출력 장치를 먼저 선택합니다. 녹화 중 장치를 바꾸지 마세요.
2. 제목을 입력하고, 모니터를 선택한 뒤 전체 화면 또는 **영역 드래그 선택**을 누릅니다.
3. 시스템 소리를 체크하고 필요하면 기본 입력 마이크를 함께 체크합니다.
4. 30 FPS / 표준으로 시작하고 30초 동안 영상·소리를 재생합니다.
5. 일시정지 → 재개 → 종료 / MP4 저장을 시험합니다.
6. 저장 폴더 열기로 영상과 소리, 시작·끝 싱크를 직접 확인하세요.

시스템 소리는 기본 출력 장치의 알림음 등도 포함합니다.
마이크는 Windows 개인정보 및 보안 → 마이크 → 데스크톱 앱 액세스 허용이 필요할 수 있습니다.
앱은 시스템 설정을 자동으로 바꾸지 않습니다.
Ctrl+Shift+R: 시작 / Ctrl+Shift+P: 일시정지·재개 / Ctrl+Shift+S: 종료.
단축키는 **앱에 포커스가 있을 때만** 동작하며 전역 단축키는 미구현입니다.
영역 이동·크기 변경은 재선택으로 합니다. 앱 창은 녹화 영역 밖으로 옮기세요.
테두리·앱 창 자체가 녹화에서 제외되는 것은 보장하지 않습니다.

## 파일명, 임시 저장 및 복구

제목은 `Options.title` → 세션의 `title` → `safe_title()` → 최종 MP4 이름으로 연결합니다.
세션에 `title_source: manual`도 기록하므로 이후 창 제목/OCR 인식 결과를 같은 경로에
연결할 수 있습니다. 현재 자동 인식은 미구현입니다.
금지문자·예약어를 정리하고 같은 파일명이 있으면 `(1)`, `(2)`를 붙입니다.

녹화 구간 MKV와 PCM WAV, 중간 MP4, 로그, `session.json`은 Temp 아래 세션별 폴더에
저장합니다. 최종 녹화 영상만 Recordings로 이동합니다. 변환 중간 영상도 Temp에 저장하고
완료 후 Converted로 이동합니다. **서로 다른 드라이브를 직접 지정한 경우** 최종 파일을
안전하게 게시하려고 대상 폴더에 잠시 `.partial` 복사본을 만든 뒤 이름을 바꿉니다.
이 경우에도 OneDrive·개발 폴더는 허용하지 않습니다. 강제 종료로 남은 `.partial` 또는
0바이트 예약 MP4는 실제 결과물인지 확인한 후 수동 정리하세요.

최종 MP4를 확인한 뒤 세션 임시 폴더는 직접 삭제하세요. 자동 정리는 하지 않습니다.
48kHz 스테레오 PCM은 장치당 약 0.69GB/시간이며 영상과 최종 MP4 공간도 필요합니다.

비정상 종료·저장 실패 시 세션을 먼저 복사하여 보존한 후, 복사본에서 복구하세요.
프로그램을 종료한 상태에서 프로젝트 CMD에서:

```bat
.venv\Scripts\python.exe -m myrecorder.cli recover "F:\MyRecorder\Temp\session-ID" --output "F:\MyRecorder\Recordings"
```

자체 생성 PCM WAV 헤더와 중간 MP4를 갱신합니다. 완전한 복구는 보장하지 않습니다.
시작 직후 종료, 손상 MKV, 전원 차단의 버퍼 손실, 디스크 고갈, 4GB 이상 WAV는 실패하거나
끝부분이 손실될 수 있습니다. 폴더를 다른 곳에 복사했다면 해당 절대 경로를 사용하세요.

## 실험용 배속 변환 (다음 단계 기능)

```bat
.venv\Scripts\python.exe -m myrecorder.cli convert "F:\MyRecorder\Recordings\강의.mp4" --recorded-speed 2 --output-speed 1
```

`settings.json`의 Converted와 Temp를 사용합니다. 원본을 보존하고 재생 시간을 약 두 배로
늘립니다. 고급 옵션 `--output "G:\변환" --temp "G:\임시"`로 명시적 변경도 가능합니다.
음높이를 최대한 유지하지만 원래 빠른 재생으로 유실된 프레임·음질을 완전히 복원하지 못합니다.
길이 검증은 실제 입 모양 싱크나 청감 검사를 대체하지 않습니다. GUI 통합은 다음 단계입니다.

## Windows EXE 빌드

FFmpeg와 설치 준비 후 `build.bat`을 실행합니다. 이 명령은 PyInstaller를 추가 설치합니다.
`dist\MyRecorder\MyRecorder.exe`가 생성될 예정이며 **폴더 전체**가 필요합니다.
프로젝트 아래에 그대로 두면 개발 폴더의 `settings.json`을 사용합니다.
EXE를 프로젝트 밖으로 복사하면 EXE 옆을 설정 루트로 사용하므로, 이번 지정 구성에서는
이동하지 않는 것을 권장합니다. FFmpeg 탐색 시 번들 `bin`도 사용합니다.
ZIP은 소스 수정본이며 **빌드·검증된 Windows EXE는 포함하지 않습니다.**

BAT은 ASCII/CRLF, `DisableDelayedExpansion`, `cd /d "%~dp0"`, 따옴표로 감싼 Python·파일 경로를
사용합니다. 정적 검토는 완료했지만 실제 한글 OneDrive 경로의 CMD 실행은 Windows에서
추가 검증해야 합니다. 실행 파일·외부 패키지의 라이선스 조건은 각 배포처를 따릅니다.

## 구현 / 검증 현황

- 구현: 기존 녹화·오디오·영역·MP4 기능, 세 저장 폴더 분리, 설정 화면·유지, 경로 생성·검사,
  접근 실패 시 차단, 개발/OneDrive 폴더 거부, 제한적 복구, 실험용 변환 CLI.
- Linux 확인: 자동 테스트 12개, 합성 영상·오디오 결합·변환, 파일명 충돌 방지, 설정 저장·재읽기,
  한글·공백 폴더, 접근 불가 경로, Windows 경로 정책과 드라이브 부재 모사,
  서로 다른 파일시스템 게시 모사. Qt offscreen 설정 화면·녹화 차단도 확인.
- Windows 미검증: 실제 C/F드라이브 접근·생성, WASAPI 장치 소리, gdigrab, BAT·EXE,
  일시정지·재개, 30분 및 1~3시간 장시간 안정성·실제 싱크.
- 미구현: 제목 자동 인식/OCR, 전역 단축키, 테두리 직접 리사이즈, 혼합 DPI, 배속 GUI.

자세한 구조는 `docs/ARCHITECTURE.md`, 테스트 절차는 `docs/WINDOWS_TEST.md`를 참고하세요.
