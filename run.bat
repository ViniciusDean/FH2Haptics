@echo off
rem FH2 Haptics settings window. Runs the real pythonw.exe of the Python behind
rem HorizonHaptics' venv (the venv's own pythonw.exe opens a console window).
setlocal
cd /d "%~dp0"
if "%HORIZONHAPTICS_DIR%"=="" set "HORIZONHAPTICS_DIR=%~dp0..\HorizonHaptics"
set "VENV=%HORIZONHAPTICS_DIR%\.venv"
set "PYHOME="
for /f "tokens=1,* delims==" %%a in ('findstr /b /c:"home" "%VENV%\pyvenv.cfg"') do set "PYHOME=%%b"
if defined PYHOME set "PYHOME=%PYHOME:~1%"
set "FH2_SITE=%VENV%\Lib\site-packages"
if exist "%PYHOME%\pythonw.exe" (
    start "" "%PYHOME%\pythonw.exe" "%~dp0fh2_gui.py"
) else (
    start "" "%VENV%\Scripts\pythonw.exe" "%~dp0fh2_gui.py"
)
