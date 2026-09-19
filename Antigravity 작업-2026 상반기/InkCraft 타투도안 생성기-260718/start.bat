@echo off
chcp 65001 >nul
title InkCraft Launcher
echo ========================================
echo   InkCraft (타투 도안 생성기) 시작
echo ========================================

REM ① API 프록시 서버 (포트 8789)
start "InkCraft-Proxy" cmd /k "cd /d %~dp0server && node index.js"

REM ② 웹앱 (포트 5175)
start "InkCraft-Web" cmd /k "cd /d %~dp0web && npm run dev"

echo.
echo 서버 2개를 새 창으로 띄웠습니다.
echo 잠시 후 브라우저가 열립니다...
timeout /t 6 /nobreak >nul
start http://localhost:5175
exit
