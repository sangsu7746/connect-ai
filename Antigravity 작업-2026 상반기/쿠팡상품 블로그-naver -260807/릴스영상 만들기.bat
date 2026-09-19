@echo off
REM Korean text is printed from Python only. CMD parses this file as CP949 and
REM breaks on Korean echo lines, so keep this file ASCII-only.
chcp 65001 > nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set NoDefaultCurrentDirectoryInExePath=
cd /d "%~dp0"

python video_pipeline.py %*

echo.
pause
