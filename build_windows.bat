@echo off
echo.
echo [WoT Maneuvers Tracker] Building Windows Executable...
echo.

REM Check for Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Python not found. Please install Python 3.10+ from python.org
    pause
    exit /b
)

echo [+] Installing dependencies...
pip install pyinstaller pandas openpyxl watchdog requests

echo [+] Building EXE...
pyinstaller --noconsole --onefile --windowed --name "WoT Maneuvers Tracker" main1.py

if %errorlevel% equ 0 (
    echo.
    echo [OK] Success! Your EXE is in the 'dist' folder.
) else (
    echo [!] Build failed.
)

pause
