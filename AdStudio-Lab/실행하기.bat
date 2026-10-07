@echo off
chcp 65001 >nul
title AdStudio - AI 광고 영상 제작
cd /d "%~dp0"

echo.
echo [1/2] AI 프록시(Firebase 에뮬레이터)를 확인합니다...

rem 이미 켜져 있으면(포트 5001 사용 중) 새로 띄우지 않는다
netstat -an | findstr ":5001" | findstr "LISTENING" >nul
if %errorlevel%==0 (
    echo      이미 켜져 있어요 - 그대로 사용합니다.
    goto start_dev
)

echo      새 창에서 AI 프록시를 시작합니다. 그 창은 닫지 마세요!
start "AdStudio - AI 프록시 (닫지 마세요)" cmd /k "npm run dev:proxy"

echo      프록시가 켜질 때까지 기다리는 중...
set /a tries=0
:wait_proxy
timeout /t 1 /nobreak >nul
netstat -an | findstr ":5001" | findstr "LISTENING" >nul
if %errorlevel%==0 goto proxy_ready
set /a tries+=1
if %tries% lss 30 goto wait_proxy
echo.
echo      30초가 지나도 프록시 시작이 확인되지 않았어요.
echo      "AI 프록시" 창에 오류 메시지가 있는지 확인해주세요.
echo      개발 서버는 계속 시작합니다 - AI 기능은 프록시가 켜진 뒤부터 동작해요.
goto start_dev

:proxy_ready
echo      프록시 준비 완료!

:start_dev
echo.
echo [2/2] AdStudio 개발 서버를 시작합니다...
echo 브라우저가 자동으로 열립니다. 이 창을 닫으면 개발 서버도 종료됩니다.
echo (AI 기능을 쓰는 동안에는 "AI 프록시" 창도 함께 켜두세요.)
echo.

call npm run dev -- --open
pause
