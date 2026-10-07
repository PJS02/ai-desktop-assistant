@echo off
setlocal
cd /d "%~dp0"
set "HAND_LAB_PYTHON=%~dp0..\.venv\Scripts\python.exe"
if not exist "%HAND_LAB_PYTHON%" (
    echo Project Python not found. See hand_landmark_lab\README.md.
    pause
    exit /b 1
)
"%HAND_LAB_PYTHON%" app.py %*
if errorlevel 1 pause
