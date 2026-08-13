@echo off
chcp 65001 >nul
echo 🚀 블로기이 AI 마스터 실행 중... 잠시만 기다려주세요!
cd /d "D:\Antigravity 작업-2026 상반기\NotebookLM MCP-naver"
call .venv\Scripts\activate.bat
python dashboard.py
pause
