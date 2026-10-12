@echo off
title FH2 Haptics
cd /d "%~dp0"
if "%HORIZONHAPTICS_DIR%"=="" set "HORIZONHAPTICS_DIR=%~dp0..\HorizonHaptics"
"%HORIZONHAPTICS_DIR%\.venv\Scripts\python.exe" "%~dp0fh2_haptics.py"
pause
