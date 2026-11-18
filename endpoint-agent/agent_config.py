import os
import uuid
import platform
import socket
from pathlib import Path


def _load_root_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
    except Exception:
        pass


def _detect_os_info() -> tuple:
    system = platform.system().lower()
    if system == "windows":
        os_name = "Windows"
        os_version = f"Windows {platform.release()} ({platform.version()})"
        prefix = "win"
    elif system == "linux":
        os_name = "Linux"
        pretty_name = None
        os_release = Path("/etc/os-release")
        if os_release.exists():
            try:
                for line in os_release.read_text(encoding="utf-8").splitlines():
                    if line.startswith("PRETTY_NAME="):
                        pretty_name = line.split("=", 1)[1].strip('"').strip("'")
                        break
            except Exception:
                pass
        os_version = pretty_name or f"Linux {platform.release()}"
        prefix = "lnx"
    else:
        os_name = platform.system()
        os_version = platform.platform()
        prefix = "agt"

    return os_name, os_version, prefix


class AgentConfig:
    def __init__(self):
        base_dir = Path(__file__).resolve().parent
        _load_root_env(base_dir.parent / ".env")

        self.server_url = os.getenv("CENTRAL_SERVER_URL", "http://127.0.0.1:8000")
        self.agent_uuid_file = base_dir / "agent_identity.txt"
        self.os_name, self.os_version, self._prefix = _detect_os_info()
        self.agent_uuid = self._load_or_create_uuid()
        self.hostname = socket.gethostname()
        self.agent_version = "1.0.0"
        self.db_path = str(base_dir / "agent_local.db")
        self.heartbeat_interval_sec = int(os.getenv("AGENT_HEARTBEAT_INTERVAL", "30"))
        self.sync_interval_sec = int(os.getenv("AGENT_SYNC_INTERVAL", "15"))
        self.mock_mode = os.getenv("REMEDIATION_MOCK_MODE", "false").lower() == "true"
        self.offline_check_interval_sec = int(os.getenv("AGENT_OFFLINE_CHECK_INTERVAL", "30"))
        self.remediation_cooldown_sec = int(os.getenv("AGENT_REMEDIATION_COOLDOWN", "120"))
        self.max_remediation_retries = int(os.getenv("AGENT_MAX_REMEDIATION_RETRIES", "3"))
        self.allowlisted_tools = ["enable_adapter", "renew_dhcp", "flush_dns_cache", "restart_approved_service"]

    def _load_or_create_uuid(self) -> str:
        if self.agent_uuid_file.exists():
            try:
                existing = self.agent_uuid_file.read_text(encoding="utf-8").strip()
                if existing:
                    return existing
            except Exception:
                pass
        new_id = f"{self._prefix}-{uuid.uuid4().hex[:12]}"
        try:
            self.agent_uuid_file.write_text(new_id, encoding="utf-8")
        except Exception:
            pass
        return new_id


agent_config = AgentConfig()
