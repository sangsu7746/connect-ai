@echo off
chcp 65001 >nul
title Tistory - Fix Title and Category
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -X utf8 -u "fix_tistory_meta.py" 20
) else (
  python -X utf8 -u "fix_tistory_meta.py" 20
)
echo.
pause
endlocal
