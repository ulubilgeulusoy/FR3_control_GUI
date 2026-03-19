@echo off
setlocal

cd /d "%~dp0"

set "SCRIPT=%~dp0FR3_control_GUI.py"
set "ENV_PYTHONW=C:\Users\Investment\miniconda3\envs\computer_vision\pythonw.exe"
set "ENV_PYTHON=C:\Users\Investment\miniconda3\envs\computer_vision\python.exe"

if not exist "%SCRIPT%" (
    echo Could not find "%SCRIPT%".
    pause
    exit /b 1
)

if exist "%ENV_PYTHONW%" (
    "%ENV_PYTHONW%" "%SCRIPT%"
    if %errorlevel%==0 goto :success
)

if exist "%ENV_PYTHON%" (
    "%ENV_PYTHON%" "%SCRIPT%"
    if %errorlevel%==0 goto :success
)

echo Unable to launch the GUI with the computer_vision environment.
echo Expected Python at:
echo %ENV_PYTHONW%
echo or
echo %ENV_PYTHON%
pause
exit /b 1

:success
exit /b 0
