@echo off
title SmartInvoice AI
cd /d "%~dp0"

REM Reuse zara-free venv (has flask + requests)
set "PY=..\zara-free\.venv\Scripts\python.exe"
if not exist "%PY%" (
    set "PY=.venv\Scripts\python.exe"
    if not exist "%PY%" (
        python -m venv .venv
        set "PY=.venv\Scripts\python.exe"
    )
)

REM Install if needed
%PY% -c "import flask" 2>nul
if errorlevel 1 (
    echo Installing dependencies...
    %PY% -m pip install -r requirements.txt
)

echo.
echo ==========================================
echo   SmartInvoice AI - Launching...
echo ==========================================
echo.
echo   Open in browser:  http://localhost:8765
echo.
echo   Press Ctrl+C in this window to stop.
echo.

%PY% backend\app.py
pause