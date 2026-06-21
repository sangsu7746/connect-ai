@echo off
chcp 65001 > nul
echo.
echo ╔═══════════════════════════════════════════════╗
echo ║   API Key 자동화 프로그램 - EXE 빌드          ║
echo ║   (PyArmor 난독화 + PyInstaller 패키징)       ║
echo ╚═══════════════════════════════════════════════╝
echo.

:: 가상환경 활성화
call .venv\Scripts\activate
if %errorlevel% neq 0 (
    echo [ERROR] 가상환경 활성화 실패. setup.bat을 먼저 실행하세요.
    pause
    exit /b 1
)

:: 이전 빌드 정리
echo [1/4] 이전 빌드 정리 중...
if exist dist\APIKeyAutomator (
    rmdir /s /q dist\APIKeyAutomator
)
if exist dist\pyarmor_build (
    rmdir /s /q dist\pyarmor_build
)
if exist .pyarmor\pack (
    rmdir /s /q .pyarmor\pack
)

:: PyArmor 난독화 + PyInstaller 빌드 (통합)
echo [2/4] 소스코드 난독화 및 EXE 빌드 중 (수 분 소요)...
pyarmor gen --pack onedir -O dist\pyarmor_build -r main.py

if %errorlevel% neq 0 (
    echo [ERROR] 빌드 실패!
    pause
    exit /b 1
)

:: 파일명 변경 (main.exe -> APIKeyAutomator.exe)
echo [3/4] 파일명 정리 중...
if exist dist\pyarmor_build\main\main.exe (
    ren dist\pyarmor_build\main\main.exe APIKeyAutomator.exe
    ren dist\pyarmor_build\main APIKeyAutomator
)

:: Playwright 브라우저 복사
echo [4/4] Playwright 브라우저 복사 중...
set PLAYWRIGHT_BROWSERS=%USERPROFILE%\AppData\Local\ms-playwright
if exist "%PLAYWRIGHT_BROWSERS%" (
    xcopy /E /I /Q "%PLAYWRIGHT_BROWSERS%\chromium-*" "dist\pyarmor_build\APIKeyAutomator\ms-playwright\chromium-*" 2>nul
    echo     Playwright Chromium 복사 완료
)

echo.
echo ✅ 빌드 완료! (PyArmor 난독화 적용)
echo.
echo 실행 파일 위치: dist\pyarmor_build\APIKeyAutomator\APIKeyAutomator.exe
echo.
echo 배포 시 포함 항목:
echo   - dist\pyarmor_build\APIKeyAutomator\ (전체 폴더를 ZIP으로 압축)
echo.
pause
