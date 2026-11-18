#!/usr/bin/env bash
# AISD - Ollama Server for LAN & VM Clients (Linux)
set -e

echo "===================================================================="
echo "  AISD - OLLAMA NETWORK SERVER FOR VM & LAN CLIENTS (LINUX)"
echo "===================================================================="
echo "  Binding: 0.0.0.0:11434"
echo "  Origins: *"
echo ""

export OLLAMA_HOST="0.0.0.0:11434"
export OLLAMA_ORIGINS="*"

ollama serve
