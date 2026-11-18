# AISD — Master Startup Script
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " AISD — AI-Powered IT Incident Management System" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$CurrentDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path "$CurrentDir\.."

Write-Host "Project Root: $ProjectRoot" -ForegroundColor Yellow

# Start Central Backend
Write-Host "`n[1/3] Starting AISD Central FastAPI Backend on http://127.0.0.1:8000..." -ForegroundColor Green
$BackendProcess = Start-Process -FilePath "python" -ArgumentList "run_server.py" -WorkingDirectory "$ProjectRoot\backend" -PassThru

# Start Next.js Frontend
Write-Host "[2/3] Starting Next.js Web Portal on http://127.0.0.1:3000..." -ForegroundColor Green
$FrontendProcess = Start-Process -FilePath "cmd.exe" -ArgumentList "/c npm run dev" -WorkingDirectory "$ProjectRoot\frontend" -PassThru

# Start Endpoint Agent in background
Write-Host "[3/3] Starting Local Endpoint Agent..." -ForegroundColor Green
$AgentProcess = Start-Process -FilePath "python" -ArgumentList "agent.py daemon" -WorkingDirectory "$ProjectRoot\endpoint-agent" -PassThru

Write-Host "`nAISD is now running!" -ForegroundColor Cyan
Write-Host "  Web Portal / Dashboard: http://localhost:3000" -ForegroundColor White
Write-Host "  Interactive API Docs:   http://localhost:8000/docs" -ForegroundColor White
Write-Host "  Endpoint Agent Status:  http://localhost:8000/api/agents" -ForegroundColor White
Write-Host "`nPress Ctrl+C or close the terminal windows to stop services." -ForegroundColor Gray
