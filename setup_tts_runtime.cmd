@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\setup_tts_runtime.py
) else (
  py -3.10 scripts\setup_tts_runtime.py
)
if errorlevel 1 (
  echo.
  echo TTS setup failed. Please check the message above.
  pause
  exit /b 1
)
echo.
echo TTS runtime ready. Open Settings - Voice to download models.
pause
