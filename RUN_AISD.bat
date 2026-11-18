@echo off
TITLE AISD - Fast Runner (Administrator)
COLOR 0A

:: Self-elevate to Administrator to give all necessary Windows remediation permissions
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [AISD] Requesting Administrator privileges for real Windows network remediation...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd.exe -ArgumentList '/k \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

echo ====================================================================
echo   AISD - AI-POWERED IT INCIDENT MANAGEMENT SYSTEM
echo   Launching Central Server, Endpoint Agent ^& Web Portal
echo ====================================================================
echo.
echo   Web Portal:      http://localhost:3000
echo   API Docs:        http://localhost:8000/docs
echo.
echo   Credentials:
echo     Technician:    tech@college.edu    / Tech@123
echo     Student:       student@college.edu / Student@123
echo     Administrator: admin@college.edu   / Admin@123
echo ====================================================================
echo.

:: Clear any stale/frozen AISD Backend or Frontend listeners on ports 8000 / 3000
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    echo [AISD] Stopping previous listener on port 8000 (PID %%a)...
    taskkill /PID %%a /F >nul 2>&1
)

:: Start Backend
start "AISD Backend [Port 8000]" cmd /k "cd /d "%~dp0backend" && python run_server.py"

:: Wait 3 seconds
timeout /t 3 /nobreak >nul

:: Start Windows Endpoint Agent Daemon (heartbeat + offline remediation/sync)
start "AISD Endpoint Agent" cmd /k "cd /d "%~dp0endpoint-agent" && python agent.py daemon"

:: Start Frontend (only if port 3000 isn't already bound, or restart cleanly)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":3000 " ^| findstr "LISTENING"') do (
    echo [AISD] Stopping previous listener on port 3000 (PID %%a)...
    taskkill /PID %%a /F >nul 2>&1
)
start "AISD Frontend [Port 3000]" cmd /k "cd /d "%~dp0frontend" && npm run dev"

:: Open Browser
timeout /t 4 /nobreak >nul
start http://localhost:3000

echo Services launched! Keep the opened terminal windows running.
echo To shut down, close the terminal windows.
pause
