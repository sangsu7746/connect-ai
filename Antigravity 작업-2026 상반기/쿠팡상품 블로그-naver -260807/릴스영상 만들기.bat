@echo off
REM Korean text is printed from Python only. CMD parses this file as CP949 and
REM breaks on Korean echo lines, so keep this file ASCII-only.
chcp 65001 > nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set NoDefaultCurrentDirectoryInExePath=
cd /d "%~dp0"

REM To post the same reel to several Instagram accounts in one --upload run,
REM uncomment and fill in the real usernames (comma-separated, no @, no spaces):
REM set INSTAGRAM_ACCOUNTS=headjim_01,headjim_02,headjim_03

python video_pipeline.py %*

echo.
pause
