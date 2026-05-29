@echo off
:: Check if script is running as Administrator
net session >nul 2>&1
if %errorLevel% == 0 (
    goto :run_app
) else (
    echo Requesting Administrator privileges...
    powershell -Command "Start-Process -FilePath '%0' -Verb RunAs"
    exit /b
)

:run_app
echo Starting Application as Administrator...
cd /d "%~dp0"
python app.py
pause
