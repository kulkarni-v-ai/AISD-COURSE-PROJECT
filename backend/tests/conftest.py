import sys
from pathlib import Path

# Remove any other projects' backend from sys.path
sys.path = [p for p in sys.path if "cobot" not in p.lower()]
backend_dir = str(Path(__file__).resolve().parent.parent)
if backend_dir in sys.path:
    sys.path.remove(backend_dir)
sys.path.insert(0, backend_dir)

# Clear any previously imported 'app' modules
for mod in list(sys.modules.keys()):
    if mod == "app" or mod.startswith("app."):
        del sys.modules[mod]
