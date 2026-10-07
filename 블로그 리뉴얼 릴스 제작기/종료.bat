@echo off
setlocal
set NoDefaultCurrentDirectoryInExePath=
title Blog Reels Maker - Stop
echo.
echo   Stopping Blog Reels Maker...
echo.
for %%P in (5175 8792) do (
  for /f "tokens=5" %%A in ('netstat -ano ^| findstr "LISTENING" ^| findstr ":%%P"') do (
    echo   - port %%P : killing PID %%A
    taskkill /F /PID %%A >nul 2>&1
  )
)
echo.
echo   Web and API server stopped.
echo   SD WebUI (port 7860) was left running - close its window manually if needed.
echo.
ping -n 5 127.0.0.1 >nul
