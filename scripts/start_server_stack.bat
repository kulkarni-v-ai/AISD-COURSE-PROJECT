@echo off
TITLE AISD - Central Server Stack (Laptop Host Server)
COLOR 0A

net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [AISD] Requesting Administrator privileges to bind ports and allow firewall access...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd.exe -ArgumentList '/k \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

cd /d "%~dp0\.."

echo ====================================================================
echo   AISD — CENTRAL SERVER STACK (LAPTOP SERVER FOR VM CLIENTS)
echo ====================================================================
echo.
echo Detecting Host IP Addresses for Client VMs...
powershell -NoProfile -Command "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | ForEach-Object { Write-Host ('   LAN / VM Host IP: ' + $_.IPAddress + ' (' + $_.InterfaceAlias + ')') -ForegroundColor Cyan }"
echo.
echo ====================================================================
echo   CONNECTION GUIDE FOR VM CLIENTS:
echo     Linux VMs:   ./join_lan_agent.sh http://^<YOUR_HOST_IP^>:8000
echo     Windows VMs: JOIN_LAN_AGENT.bat http://^<YOUR_HOST_IP^>:8000
echo     Web Portal:  http://localhost:3000  (or http://^<YOUR_HOST_IP^>:3000)
echo     Chatbot API: http://localhost:8000/docs
echo ====================================================================
echo.

:: 1. Clear any stale listeners on port 8000 or 3000
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":3000 " ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
)

:: 2. Start Ollama Server with 0.0.0.0 binding
echo [1/3] Starting Ollama Server on 0.0.0.0:11434...
start "AISD Ollama Server [0.0.0.0:11434]" cmd /k "set OLLAMA_HOST=0.0.0.0:11434&& set OLLAMA_ORIGINS=*&& ollama serve"

:: Wait 2 seconds
timeout /t 2 /nobreak >nul

:: 3. Start Central FastAPI Backend on 0.0.0.0:8000
echo [2/3] Starting AISD Central Backend on 0.0.0.0:8000...
start "AISD Central Backend [Port 8000]" cmd /k "cd /d "%~dp0..\backend" && python run_server.py"

:: Wait 3 seconds
timeout /t 3 /nobreak >nul

:: 4. Start Next.js Frontend
echo [3/3] Starting Web Portal Frontend on Port 3000...
start "AISD Web Portal [Port 3000]" cmd /k "cd /d "%~dp0..\frontend" && npm run dev"

echo.
echo ====================================================================
echo   AISD Central Server Stack is running!
echo   Ready to receive connections from Windows and Linux VM clients.
echo ====================================================================
pause
