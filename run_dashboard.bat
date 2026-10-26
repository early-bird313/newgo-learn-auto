@echo off
title AI Creator Studio - Facebook AI Automation
echo ========================================================
echo  Starting AI Creator Studio Facebook AI Content Dashboard...
echo ========================================================
echo.
cd /d "%~dp0"
start http://localhost:8001
.\.venv\Scripts\python -m uvicorn main:app --host 127.0.0.1 --port 8001
pause
