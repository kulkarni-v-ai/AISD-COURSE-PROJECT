import ctypes
import platform
import sys
from pathlib import Path


def disable_windows_console_quick_edit() -> None:
    """
    Disables Windows Console QuickEdit Mode so clicking inside the terminal window
    never freezes uvicorn / asyncio stdout writes.
    """
    if platform.system().lower() != "windows":
        return
    try:
        kernel32 = ctypes.windll.kernel32
        STD_INPUT_HANDLE = -10
        ENABLE_QUICK_EDIT_MODE = 0x0040
        ENABLE_EXTENDED_FLAGS = 0x0080
        handle = kernel32.GetStdHandle(STD_INPUT_HANDLE)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            new_mode = (mode.value & ~ENABLE_QUICK_EDIT_MODE) | ENABLE_EXTENDED_FLAGS
            kernel32.SetConsoleMode(handle, new_mode)
    except Exception:
        pass


# Ensure AISD backend takes top priority over any other globally linked 'app' packages
current_dir = str(Path(__file__).resolve().parent)
sys.path = [p for p in sys.path if "cobot" not in p.lower()]
if current_dir in sys.path:
    sys.path.remove(current_dir)
sys.path.insert(0, current_dir)

# Clear any already cached 'app' modules
for mod in list(sys.modules.keys()):
    if mod == "app" or mod.startswith("app."):
        del sys.modules[mod]

import uvicorn
from app.core.config import settings

if __name__ == "__main__":
    disable_windows_console_quick_edit()
    print(f"Starting AISD Central Server from {current_dir} on {settings.HOST}:{settings.PORT} (Model: {settings.OLLAMA_MODEL})...")
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=False)
