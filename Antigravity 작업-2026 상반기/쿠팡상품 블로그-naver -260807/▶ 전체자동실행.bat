@echo off
chcp 65001 >nul
title Coupang Blog - Run All
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -X utf8 -u "run_all.py"
) else (
  python -X utf8 -u "run_all.py"
)
echo.
pause
endlocal
