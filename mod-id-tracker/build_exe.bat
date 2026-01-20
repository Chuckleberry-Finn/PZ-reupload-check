@echo off
setlocal enabledelayedexpansion

REM ============================================================
REM Build DMCA Tracker EXE (PyInstaller)
REM ============================================================

cd /d "%~dp0"

set APP_NAME=DMCA-Tracker
set ENTRY=server.py

echo.
echo [1/6] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python not found on PATH.
  pause
  exit /b 1
)

echo.
echo [2/6] Installing/Upgrading build tools...
echo This may take a minute...
python -m pip install --upgrade pip
python -m pip install --upgrade pyinstaller

echo.
echo [3/6] Validating files...
if not exist "%ENTRY%" (
  echo ERROR: Missing %ENTRY%
  pause
  exit /b 1
)

if not exist "public\index.html" (
  echo ERROR: Missing public\index.html
  pause
  exit /b 1
)

if not exist "verify\verify_dmca_steam.py" (
  echo ERROR: Missing verify\verify_dmca_steam.py
  pause
  exit /b 1
)

echo.
echo [4/6] Cleaning old builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist "%APP_NAME%.spec" del /q "%APP_NAME%.spec"

echo.
echo [5/6] Building %APP_NAME%.exe ...
echo This may take several minutes...
python -m PyInstaller ^
  --onefile ^
  --console ^
  --name "%APP_NAME%" ^
  --distpath ".." ^
  --add-data "public;public" ^
  --add-data "verify;verify" ^
  --hidden-import=winreg ^
  "%ENTRY%"

if errorlevel 1 (
  echo.
  echo ERROR: Build failed.
  echo Check the output above for errors.
  pause
  exit /b 1
)

echo.
echo [6/6] Done!
echo.
echo ========================================
echo  SUCCESS!
echo ========================================
echo.
echo Output location:
echo   %cd%\%APP_NAME%.exe
echo.
echo You can now distribute this single EXE file.
echo It includes all dependencies and the web interface.
echo.
pause