@echo off
setlocal

cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 FR3_control_GUI.py
    if %errorlevel%==0 goto :success
)

where python >nul 2>nul
if %errorlevel%==0 (
    python FR3_control_GUI.py
    if %errorlevel%==0 goto :success
)

echo Unable to launch the GUI with Python.
echo Install Python for Windows and make sure `py` or `python` is available in PATH.
pause
exit /b 1

:success
