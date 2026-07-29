@echo off
title AstraQuote Lead Engine — Setup
echo.
echo ╔═══════════════════════════════════════════╗
echo ║     ASTRAQUOTE LEAD ENGINE — SETUP        ║
echo ║     Swiss B2B Lead Generation System      ║
echo ╚═══════════════════════════════════════════╝
echo.

:: Create directories
if not exist "data" mkdir data
if not exist "exports" mkdir exports
if not exist "session" mkdir session

:: Create virtual environment
if not exist "venv" (
    echo [1/3] Creating Python virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Python not found. Install Python 3.11+ from python.org
        pause
        exit /b 1
    )
) else (
    echo [1/3] Virtual environment already exists.
)

:: Activate and install
echo [2/3] Installing dependencies...
call venv\Scripts\activate.bat
pip install -r requirements.txt --quiet

if errorlevel 1 (
    echo.
    echo ERROR: Some packages failed to install.
    echo Try: pip install -r requirements.txt
    pause
    exit /b 1
)

:: Validate
echo [3/3] Validating configuration...
python main.py --validate

echo.
echo ═══════════════════════════════════════════
echo   Setup complete!
echo.
echo   To run:  python main.py
echo   Dashboard: http://localhost:8800
echo ═══════════════════════════════════════════
echo.
pause
