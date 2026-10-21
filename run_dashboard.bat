@echo off
title QueueSense Dashboard
cd /d "%~dp0"

echo ==============================================================================
echo                      QueueSense Streamlit Dashboard
echo ==============================================================================

if exist .venv\Scripts\streamlit.exe (
    set "STREAMLIT_EXE=.venv\Scripts\streamlit.exe"
) else (
    set "STREAMLIT_EXE=streamlit"
)

echo Starting QueueSense on http://localhost:8501...
echo.

%STREAMLIT_EXE% run streamlit_app.py

pause
