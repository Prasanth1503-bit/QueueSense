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
echo.
echo ==============================================================================
set /p choice="Select an option [1-4] (Default is 1): "
if "%choice%"=="" set choice=1

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
goto start_all

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

:start_monitor
echo Starting YOLO Video Monitor...
%PYTHON_EXE% monitor.py
goto end

:end
pause
