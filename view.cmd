@echo off
rem Double-click to browse what has been harvested.
cd /d "%~dp0"
if not exist ".venv\Scripts\streamlit.exe" (
  echo   Not set up yet on this machine. Start Cumulate once first - it
  echo   prepares this too - or run: uv venv ^&^& uv pip install -r requirements.txt
  pause
  exit /b 1
)
.venv\Scripts\streamlit.exe run harvest\viewer.py
if errorlevel 1 pause
