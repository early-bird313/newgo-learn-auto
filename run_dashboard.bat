@echo off
title NewGo Learn - Facebook AI Automation
echo ========================================================
echo  Starting NewGo Learn Facebook AI Content Dashboard...
echo ========================================================
echo.
cd /d "%~dp0"
start http://localhost:8001
.\.venv\Scripts\python -m uvicorn main:app --host 127.0.0.1 --port 8001
pause
