@echo off
chcp 65001 >nul
title Coupang Blog - Scheduled Run
setlocal
cd /d "%~dp0"
if not exist "logs" mkdir "logs"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -X utf8 -u "run_all.py"
) else (
  python -X utf8 -u "run_all.py"
)
endlocal
