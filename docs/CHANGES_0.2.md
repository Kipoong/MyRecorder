# 0.2 경로 설정 수정본

- Windows 개발 위치: %USERPROFILE%\OneDrive\바탕 화면\allthetest\myrecorder
- 기본 미디어 경로: F:\MyRecorder\Recordings / Converted / Temp
- QSettings 대신 개발 폴더 settings.json, 최초 실행 시 생성.
- 세 폴더 설정 다이얼로그, 경로 생성 및 쓰기 검사, 재시작 후 유지.
- 드라이브 누락 시 경고와 경로 설정 안내; C드라이브·cwd 자동 대체 없음.
- OneDrive/개발 폴더를 미디어 경로로 지정하면 거부.
- 녹화 세션과 중간 영상은 Temp, 최종 녹화는 Recordings, 변환 결과는 Converted.
- 다른 볼륨 게시를 위한 대상 .partial 복사 및 실패 시 정리.
- 제목 출처와 경로를 세션에 기록. 기존 화면·오디오·일시정지 기능 소스 유지.
- BAT의 자체 경로·Python·FFmpeg 경로 인용과 delayed expansion 처리 점검.
- Linux unittest 12개 및 Qt offscreen smoke 통과. Windows 실기·BAT·EXE 미검증.
- ZIP은 소스와 설명서만 포함. Python, 외부 패키지, FFmpeg, 완성 EXE 미포함.
