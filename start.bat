@echo off
chcp 65001 > nul
echo ============================================
echo  Sales Tool - Starting...
echo ============================================
echo.

set PYTHON=C:\Users\nishikawa\AppData\Local\Programs\Python\Python312\python.exe

cd /d %~dp0

if not exist .env (
    echo [ERROR] .env file not found.
    pause
    exit /b 1
)

REM Check if server is already running on port 8000
netstat -ano | findstr ":8000" | findstr "LISTENING" > nul 2>&1
if %errorlevel%==0 (
    echo [INFO] Server is already running on port 8000.
    echo Opening browser...
    start "" "http://localhost:8000"
    pause
    exit /b 0
)

echo Starting server...
start "Sales Tool Server" "%PYTHON%" main.py

echo Waiting for server to start...
timeout /t 5 /nobreak > nul

echo Opening browser: http://localhost:8000
start "" "http://localhost:8000"

echo.
echo ============================================
echo  Server started!
echo  URL: http://localhost:8000
echo  To stop: Close the "Sales Tool Server" window
echo ============================================
pause
