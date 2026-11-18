#!/usr/bin/env bash
# AISD Linux LAN Endpoint Agent & Chatbot Launcher
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

SERVER_URL="$1"
if [ -z "$SERVER_URL" ]; then
    echo "===================================================================="
    echo "  AISD LINUX ENDPOINT AGENT & CHATBOT - JOIN CENTRAL SERVER"
    echo "===================================================================="
    echo "  Enter Central Server URL (e.g. http://192.168.1.50:8000)"
    echo "  Or press ENTER for default [http://127.0.0.1:8000]"
    echo ""
    read -rp "Central Server URL: " SERVER_URL
fi

if [ -z "$SERVER_URL" ]; then
    SERVER_URL="http://127.0.0.1:8000"
fi

echo ""
echo "Select Run Mode:"
echo "  [1] Start Background Agent Daemon (Heartbeat + Auto-Remediation + Sync)"
echo "  [2] Start Interactive IT Support Chatbot Client"
echo "  [3] Run One-Time Diagnostics & Rule Evaluation"
echo ""
read -rp "Select mode [1/2/3] (Default: 1): " CHOICE

if [ "$CHOICE" = "2" ]; then
    echo "[AISD] Starting Interactive Chatbot Client..."
    python3 chatbot_client.py --server "$SERVER_URL"
elif [ "$CHOICE" = "3" ]; then
    echo "[AISD] Running diagnostic scan..."
    python3 agent.py --server "$SERVER_URL" diagnose-and-remediate
else
    echo "[AISD Agent] Connecting daemon to Central Server: $SERVER_URL"
    python3 agent.py --server "$SERVER_URL" daemon
fi
