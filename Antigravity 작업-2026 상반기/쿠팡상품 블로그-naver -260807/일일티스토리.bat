@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -X utf8 "daily_tistory.py"
) else (
  python -X utf8 "daily_tistory.py"
)
pause
endlocal
