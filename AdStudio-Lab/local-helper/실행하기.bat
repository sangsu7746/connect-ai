@echo off
cd /d "%~dp0"

where node >nul 2>nul
if errorlevel 1 (
  echo Node.js is required. Please install from https://nodejs.org
  pause
  exit /b 1
)

if not exist node_modules (
  echo [AdStudio Helper] First run: installing packages... ^(takes a few minutes^)
  call npm install
  call npx playwright install chromium
)

echo [AdStudio Helper] Starting on http://127.0.0.1:8791 - keep this window open.
node server.js
pause
