@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
if errorlevel 1 goto fail
set "MYRECORDER_HOME=%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" goto missing
"%~dp0.venv\Scripts\python.exe" -m myrecorder
if errorlevel 1 goto fail
exit /b 0
:missing
echo Run install.bat first.
:fail
pause
exit /b 1
