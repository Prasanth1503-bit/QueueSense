@echo off
title QueueSense Unified Launcher
cd /d "%~dp0"

echo ==============================================================================
echo                      QueueSense Smart Queue Intelligence
echo ==============================================================================
echo.
echo   1. Start Complete System (Flask Web + Hardware Bridge + Streamlit)
echo   2. Start Streamlit Dashboard (http://localhost:8501)
echo   3. Start Flask Web Server & Hardware Bridge (http://localhost:5000)
echo   4. Start YOLO AI Video Monitor (monitor.py)
echo   5. ⚡ Start 100% Offline College Demo Mode (Flask + Hardware Bridge - No Internet Needed)
echo.
echo ==============================================================================
set /p choice="Select an option [1-5] (Default is 3 for Flask): "
if "%choice%"=="" set choice=3

if exist .venv\Scripts\python.exe (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
    set "STREAMLIT_EXE=.venv\Scripts\streamlit.exe"
) else (
    set "PYTHON_EXE=python"
    set "STREAMLIT_EXE=streamlit"
)

if "%choice%"=="1" goto start_all
if "%choice%"=="2" goto start_streamlit
if "%choice%"=="3" goto start_flask
if "%choice%"=="4" goto start_monitor
if "%choice%"=="5" goto start_offline_flask
goto start_flask

:start_all
echo Starting Local Flask Web Server on http://localhost:5000...
start "QueueSense Flask Server" %PYTHON_EXE% app.py
timeout /t 2 >nul
echo Starting Streamlit Dashboard on http://localhost:8501...
%STREAMLIT_EXE% run streamlit_app.py
goto end

:start_streamlit
echo Starting Streamlit Dashboard on http://localhost:8501...
%STREAMLIT_EXE% run streamlit_app.py
goto end

:start_flask
echo Starting Flask Server & Hardware Bridge on http://localhost:5000...
%PYTHON_EXE% app.py
goto end

:start_offline_flask
echo ==============================================================================
echo [OFFLINE MODE] Forcing 100%% Local SQLite Database (Zero Internet Required)
echo ==============================================================================
set OFFLINE_MODE=1
set USE_LOCAL_DB=1
echo Starting Flask Server on http://localhost:5000...
start "QueueSense Flask Server (Offline)" %PYTHON_EXE% app.py
timeout /t 2 >nul
echo Starting YOLO Video Monitor...
%PYTHON_EXE% monitor.py
goto end

:start_monitor
echo Starting YOLO Video Monitor...
%PYTHON_EXE% monitor.py
goto end

:end
pause
