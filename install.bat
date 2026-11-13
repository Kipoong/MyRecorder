@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
if errorlevel 1 goto fail
set "MYRECORDER_HOME=%~dp0"
py -3.12 -m venv "%~dp0.venv"
if errorlevel 1 goto fail
"%~dp0.venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto fail
"%~dp0.venv\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 goto fail
echo Dependencies installed. Put ffmpeg.exe and ffprobe.exe into bin.
echo Run run.bat. Storage defaults to F:\MyRecorder, never this folder.
pause
exit /b 0
:fail
echo Install failed. Check Python 3.12 x64 and folder permissions.
pause
exit /b 1
