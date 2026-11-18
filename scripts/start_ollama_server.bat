@echo off
TITLE AISD - Ollama Server (Binding 0.0.0.0:11434 for LAN & VM Clients)
COLOR 0B

echo ====================================================================
echo   AISD - OLLAMA NETWORK SERVER FOR VM & LAN CLIENTS
echo ====================================================================
echo.
echo   Configuring Ollama to accept remote connections from VMs and LAN...
echo   Binding: 0.0.0.0:11434 (All network interfaces)
echo   Allowed Origins: * (All origins permitted)
echo.

set OLLAMA_HOST=0.0.0.0:11434
set OLLAMA_ORIGINS=*

ollama serve

pause
