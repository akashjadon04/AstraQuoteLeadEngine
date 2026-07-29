@echo off
title AstraQuote Lead Engine Launcher
cls
echo.
echo ╔═══════════════════════════════════════════╗
echo ║     ASTRAQUOTE LEAD ENGINE LAUNCHER       ║
echo ║     Swiss B2B Lead Generation System      ║
echo ╚═══════════════════════════════════════════╝
echo.
echo  [1] RUN LEADS GENERATOR (Crawl real-world Swiss trade leads)
echo  [2] START DASHBOARD UI  (Launch local server and view leads database)
echo  [3] RUN SYSTEM VALIDATION (Verify config keys and settings)
echo  [4] EXIT
echo.
set /p choice="Select an option [1-4]: "

if "%choice%"=="1" goto run_generator
if "%choice%"=="2" goto run_dashboard
if "%choice%"=="3" goto run_validation
if "%choice%"=="4" goto end

:run_generator
echo.
echo Starting Lead Generation Pipeline...
call venv\Scripts\activate.bat
python main.py
pause
goto end

:run_dashboard
echo.
echo Launching Dashboard UI...
call venv\Scripts\activate.bat
python main.py --dashboard
pause
goto end

:run_validation
echo.
echo Checking system config...
call venv\Scripts\activate.bat
python main.py --validate
echo.
pause
goto end

:end
echo.
echo Goodbye!
echo.
