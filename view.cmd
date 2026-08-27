@echo off
rem Double-click to browse what has been harvested.
cd /d "%~dp0"
.venv\Scripts\streamlit.exe run harvest\viewer.py
