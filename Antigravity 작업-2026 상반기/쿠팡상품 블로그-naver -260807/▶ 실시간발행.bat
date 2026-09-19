@echo off
chcp 65001 >nul
title Coupang Blog - Publish Now
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -X utf8 -u "publish_now.py"
) else (
  python -X utf8 -u "publish_now.py"
)
endlocal
