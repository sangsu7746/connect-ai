@echo off
setlocal
set NoDefaultCurrentDirectoryInExePath=
title Blog Reels Maker
cd /d "%~dp0"

echo.
echo   == Blog Reels Maker ==
echo.

echo   [1/3] Stable Diffusion WebUI (port 7860)
netstat -an | findstr "LISTENING" | findstr ":7860" >nul 2>&1
if errorlevel 1 (
  if exist "D:\sd-webui\start-api.bat" (
    start "SD WebUI" cmd /c "D:\sd-webui\start-api.bat"
    echo         starting - first load takes 1-2 min
  ) else (
    echo         SKIPPED - D:\sd-webui\start-api.bat not found
  )
) else (
  echo         already running
)

echo   [2/3] API server (port 8792)
netstat -an | findstr "LISTENING" | findstr ":8792" >nul 2>&1
if errorlevel 1 (
  start "Blog Reels Server" /D "%~dp0" cmd /c "server\.venv\Scripts\python.exe -m uvicorn main:app --app-dir server --port 8792"
  echo         starting
) else (
  echo         already running
)

echo   [3/3] Web UI (port 5175)
netstat -an | findstr "LISTENING" | findstr ":5175" >nul 2>&1
if errorlevel 1 (
  start "Blog Reels Web" /D "%~dp0web" cmd /c "npm run dev"
  echo         starting
) else (
  echo         already running
)

echo.
echo   Opening browser...
ping -n 7 127.0.0.1 >nul
start "" http://localhost:5175
echo.
echo   Done. Keep the opened windows running.
echo   To stop everything, run the stop script in this folder.
echo.
ping -n 4 127.0.0.1 >nul
