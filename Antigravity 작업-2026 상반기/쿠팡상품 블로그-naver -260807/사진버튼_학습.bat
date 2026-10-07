@echo off
chcp 65001 > nul
echo.
echo =====================================================
echo  네이버 사진 버튼 경로 학습 모드
echo  (Chrome 브라우저가 자동으로 열립니다)
echo =====================================================
echo.
cd /d "%~dp0"
python learn_photo_button.py
pause
