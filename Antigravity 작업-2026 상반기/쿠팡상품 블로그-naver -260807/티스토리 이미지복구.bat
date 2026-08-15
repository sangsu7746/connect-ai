@echo off
chcp 65001 >nul
title 티스토리 발행글 이미지 복구
setlocal
cd /d "%~dp0"
echo.
echo  티스토리 발행글 이미지 복구
echo  ------------------------------------------------
echo  브라우저가 열리면 티스토리(카카오)에 로그인하세요.
echo  "로그인 상태 유지"를 꼭 체크해 주세요.
echo.
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -X utf8 -u "fix_tistory_images.py"
) else (
  python -X utf8 -u "fix_tistory_images.py"
)
echo.
pause
endlocal
