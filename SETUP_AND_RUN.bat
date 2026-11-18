@echo off
TITLE AISD — 1-Click Automated Setup and Runner (Administrator)
COLOR 0B

:: Self-elevate to Administrator to give all necessary Windows remediation permissions
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [AISD] Requesting Administrator privileges for real Windows remediation execution...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd.exe -ArgumentList '/k \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

echo ====================================================================
echo   AISD - AI-POWERED IT INCIDENT MANAGEMENT SYSTEM
echo   Automated Setup ^& Run for Team Members
echo ====================================================================
echo.

:: 1. Check Python
echo [1/4] Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH!
    echo Please install Python 3.10+ from https://www.python.org/downloads/
    echo Make sure to check "Add python.exe to PATH" during installation.
    pause
    exit /b 1
)
python --version

:: 2. Check Node.js
echo.
echo [2/4] Checking Node.js installation...
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Node.js is not installed or not in PATH!
    echo Please install Node.js 18+ from https://nodejs.org/
    pause
    exit /b 1
)
node --version

:: 3. Install Python Dependencies
echo.
echo [3/4] Installing Python Backend dependencies...
cd backend
python -m pip install -r requirements.txt greenlet
if %errorlevel% neq 0 (
    echo [WARNING] Some pip packages had issues. Continuing...
)
cd ..

:: 4. Install Frontend Dependencies
echo.
echo [4/4] Installing Next.js Frontend dependencies...
cd frontend
call npm install
cd ..

echo.
echo ====================================================================
echo   SETUP COMPLETE! Starting AISD Services...
echo ====================================================================
echo.
echo   Web Portal:      http://localhost:3000
echo   API Docs:        http://localhost:8000/docs
echo.
echo   Technician:      tech@college.edu   / Tech@123
echo   Student:         student@college.edu / Student@123
echo   Administrator:   admin@college.edu  / Admin@123
echo ====================================================================
echo.

:: Clear any stale listener on port 8000 / 3000
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000 " ^| findstr "LISTENING"') do taskkill /PID %%a /F >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":3000 " ^| findstr "LISTENING"') do taskkill /PID %%a /F >nul 2>&1

:: Start Backend
start "AISD Central Backend (FastAPI)" cmd /k "cd /d "%~dp0backend" && python run_server.py"

:: Wait 3 seconds
timeout /t 3 /nobreak >nul

:: Start Endpoint Agent
start "AISD Endpoint Agent" cmd /k "cd /d "%~dp0endpoint-agent" && python agent.py daemon"

:: Start Frontend
start "AISD Web Portal (Next.js)" cmd /k "cd /d "%~dp0frontend" && npm run dev"

:: Open Browser
timeout /t 4 /nobreak >nul
start http://localhost:3000

echo Services are running in their respective windows.
echo To stop, simply close the backend and frontend command windows.
pause
