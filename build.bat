@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
if errorlevel 1 goto fail
set "MYRECORDER_HOME=%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" goto missingpython
if not exist "%~dp0bin\ffmpeg.exe" goto missing
if not exist "%~dp0bin\ffprobe.exe" goto missing
"%~dp0.venv\Scripts\python.exe" -m pip install "pyinstaller>=6.10,<7"
if errorlevel 1 goto fail
"%~dp0.venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --console --name MyRecorder --collect-all pyaudiowpatch --manifest "%~dp0windows.manifest" --distpath "%~dp0dist" --workpath "%~dp0build" --specpath "%~dp0." --add-binary "%~dp0bin\ffmpeg.exe;bin" --add-binary "%~dp0bin\ffprobe.exe;bin" "%~dp0launcher.py"
if errorlevel 1 goto fail
echo Build complete: dist\MyRecorder\MyRecorder.exe
echo Keep the entire dist\MyRecorder folder. Configuration stays in project root.
pause
exit /b 0
:missingpython
echo Run install.bat first.
goto fail
:missing
echo Place ffmpeg.exe and ffprobe.exe in bin first.
:fail
pause
exit /b 1
