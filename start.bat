@echo off
chcp 65001 >nul
cd /d "%~dp0"

set PORT=8000

echo [1/3] Checking port %PORT%...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT%" ^| findstr "LISTENING"') do (
    echo [INFO] Killing process on port %PORT%, PID=%%a
    taskkill /F /PID %%a
)

echo [2/3] Waiting for port %PORT% to be released...
for /l %%i in (1,1,15) do (
    netstat -ano | findstr ":%PORT%" | findstr "LISTENING" >nul
    if errorlevel 1 goto port_free
    timeout /t 1 /nobreak >nul
)

echo [ERROR] Port %PORT% is still occupied:
netstat -ano | findstr ":%PORT%" | findstr "LISTENING"
pause
exit /b 1

:port_free
echo [3/3] Starting service...
"%USERPROFILE%\miniconda3\python.exe" src\main.py
