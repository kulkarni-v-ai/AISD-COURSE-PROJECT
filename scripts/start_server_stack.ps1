# AISD — Central Server Stack Launcher (PowerShell)
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " AISD — Central Server Stack (Laptop Server for VMs)" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$CurrentDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path "$CurrentDir\.."

Write-Host "`nDetecting Host IP Addresses for Client VMs..." -ForegroundColor Yellow
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } | ForEach-Object {
    Write-Host "   LAN / VM Host IP: $($_.IPAddress) ($($_.InterfaceAlias))" -ForegroundColor Green
}

Write-Host "`nConnection Guide for VM Clients:" -ForegroundColor White
Write-Host "  Linux VMs:   ./join_lan_agent.sh http://<YOUR_HOST_IP>:8000" -ForegroundColor Gray
Write-Host "  Windows VMs: JOIN_LAN_AGENT.bat http://<YOUR_HOST_IP>:8000" -ForegroundColor Gray
Write-Host "  Web Portal:  http://localhost:3000 (or http://<YOUR_HOST_IP>:3000)" -ForegroundColor Gray

# 1. Start Ollama with remote LAN binding
Write-Host "`n[1/3] Starting Ollama Server (OLLAMA_HOST=0.0.0.0:11434)..." -ForegroundColor Green
$OllamaEnv = @{ "OLLAMA_HOST" = "0.0.0.0:11434"; "OLLAMA_ORIGINS" = "*" }
Start-Process -FilePath "cmd.exe" -ArgumentList "/k set OLLAMA_HOST=0.0.0.0:11434 && set OLLAMA_ORIGINS=* && ollama serve"

Start-Sleep -Seconds 2

# 2. Start Central Backend
Write-Host "[2/3] Starting AISD Central FastAPI Backend on http://0.0.0.0:8000..." -ForegroundColor Green
Start-Process -FilePath "python" -ArgumentList "run_server.py" -WorkingDirectory "$ProjectRoot\backend"

Start-Sleep -Seconds 3

# 3. Start Next.js Frontend
Write-Host "[3/3] Starting Next.js Web Portal on http://0.0.0.0:3000..." -ForegroundColor Green
Start-Process -FilePath "cmd.exe" -ArgumentList "/c npm run dev" -WorkingDirectory "$ProjectRoot\frontend"

Write-Host "`nAISD Central Server Stack is now running!" -ForegroundColor Cyan
Write-Host "Ready to serve local agents and VM clients." -ForegroundColor White
