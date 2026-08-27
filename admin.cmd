@echo off
rem The whole record - everyone's. Yours only: it reads the secret key, which
rem bypasses every row-level policy. Never hand this file or its output out.
cd /d "%~dp0"
.venv\Scripts\python.exe -m harvest admin
if errorlevel 1 (
  pause
  exit /b 1
)
start "" out\admin.html
