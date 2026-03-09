@echo off
cd /d "%~dp0"

echo [1/3] Checking port 8000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
    echo [INFO] Killing process on port 8000 (PID: %%a)
    taskkill /F /PID %%a >nul 2>&1
)

echo [2/3] Starting service...
"%USERPROFILE%\miniconda3\python.exe" src\main.py
