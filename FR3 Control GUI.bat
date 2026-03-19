@echo off
setlocal

cd /d "%~dp0"

set "SCRIPT=%~dp0FR3_control_GUI.py"

if not exist "%SCRIPT%" (
    echo Could not find "%SCRIPT%".
    pause
    exit /b 1
)

where pyw >nul 2>nul
if %errorlevel%==0 (
    pyw -3 "%SCRIPT%"
    if %errorlevel%==0 goto :success
)

where pythonw >nul 2>nul
if %errorlevel%==0 (
    pythonw "%SCRIPT%"
    if %errorlevel%==0 goto :success
)

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 "%SCRIPT%"
    if %errorlevel%==0 goto :success
)

where python >nul 2>nul
if %errorlevel%==0 (
    python "%SCRIPT%"
    if %errorlevel%==0 goto :success
)

echo Unable to launch the GUI with Python.
echo Make sure Python for Windows is installed and registered with `py`, `pyw`, `python`, or `pythonw`.
pause
exit /b 1

:success
exit /b 0
