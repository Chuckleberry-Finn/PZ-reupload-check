@echo off
echo ========================================
echo  Project Zomboid Mod Tracker Launcher
echo ========================================
echo.

REM Check if Python is installed
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python is not installed!
    pause
    exit /b 1
)

REM Check Python version
echo [INFO] Checking Python installation...
python --version
echo.

REM Check if public folder exists
if not exist "public\" (
    echo [ERROR] public folder not found!
    pause
    exit /b 1
)

REM Check if server.py exists
if not exist "server.py" (
    echo [ERROR] server.py not found!
    pause
    exit /b 1
)

REM Kill any existing Python processes that might be blocking the port
echo [INFO] Checking for existing server processes...
taskkill /F /IM python.exe /FI "WINDOWTITLE eq *server.py*" >nul 2>&1

REM Start the server (NOT in background - so we can see errors)
echo [INFO] Starting the Mod Tracker server...
echo.
echo ========================================
echo  Server will start on: http://localhost:3000
echo ========================================
echo.
echo Opening browser in 3 seconds...
echo.

REM Open browser after delay (in background)
start "" cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:3000"

REM Run the server in foreground so we can see any errors
python server.py

REM If we get here, server stopped
echo.
echo [INFO] Server has stopped.
pause