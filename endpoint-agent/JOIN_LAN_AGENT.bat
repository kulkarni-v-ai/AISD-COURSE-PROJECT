@echo off
TITLE AISD LAN Endpoint Agent & Chatbot (Administrator)
COLOR 0A

net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [AISD Agent] Requesting Administrator privileges for Windows network remediation...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd.exe -ArgumentList '/k \"\"%~f0\"\" %*' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

set SERVER_URL=%1
if "%SERVER_URL%"=="" (
    echo ====================================================================
    echo   AISD ENDPOINT AGENT & CHATBOT - JOIN CENTRAL SERVER
    echo ====================================================================
    echo   Enter Central Server URL (e.g. http://192.168.1.50:8000)
    echo   Or press ENTER for default [http://127.0.0.1:8000]
    echo.
    set /p SERVER_URL="Central Server URL: "
)

if "%SERVER_URL%"=="" (
    set SERVER_URL=http://127.0.0.1:8000
)

echo.
echo Select Run Mode:
echo   [1] Start Background Agent Daemon (Heartbeat + Auto-Remediation + Sync)
echo   [2] Start Interactive IT Support Chatbot Client
echo   [3] Run One-Time Diagnostics & Rule Evaluation
echo.
set /p CHOICE="Select mode [1/2/3] (Default: 1): "

if "%CHOICE%"=="2" (
    echo [AISD] Starting Interactive Chatbot Client...
    python chatbot_client.py --server %SERVER_URL%
) else if "%CHOICE%"=="3" (
    echo [AISD] Running diagnostic scan...
    python agent.py --server %SERVER_URL% diagnose-and-remediate
) else (
    echo [AISD Agent] Connecting daemon to Central Server: %SERVER_URL%
    python agent.py --server %SERVER_URL% daemon
)

pause
