@echo off
:: Check if script is running as Administrator
net session >nul 2>&1
if %errorLevel% == 0 (
    goto :check_deps
) else (
    echo Requesting Administrator privileges...
    powershell -Command "Start-Process -FilePath '%0' -Verb RunAs"
    exit /b
)

:check_deps
echo Checking Python dependencies...
python -c "import flask" >nul 2>&1
if %errorLevel% neq 0 (
    echo Installing Flask for LAN sync server...
    pip install flask --quiet
)
python -c "import requests" >nul 2>&1
if %errorLevel% neq 0 (
    echo Installing requests for LAN sync client...
    pip install requests --quiet
)
echo Dependencies OK.

:run_app
echo.
echo Starting PayrollPro as Administrator...
cd /d "%~dp0"
python app.py
pause
