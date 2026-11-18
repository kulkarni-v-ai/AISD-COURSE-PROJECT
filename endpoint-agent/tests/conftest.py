import sys
from pathlib import Path

# Ensure endpoint-agent directory is in sys.path
agent_dir = str(Path(__file__).resolve().parent.parent)
if agent_dir in sys.path:
    sys.path.remove(agent_dir)
sys.path.insert(0, agent_dir)
