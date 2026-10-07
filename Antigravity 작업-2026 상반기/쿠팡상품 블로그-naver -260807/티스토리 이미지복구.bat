@echo off
chcp 65001 >nul
title Tistory - Fix Images
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -X utf8 -u "fix_tistory_images.py"
) else (
  python -X utf8 -u "fix_tistory_images.py"
)
echo.
pause
endlocal
