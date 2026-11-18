import httpx
import logging
from typing import Dict, Any, List, Optional, Tuple
from agent_config import agent_config
from storage import AgentLocalStorage

logger = logging.getLogger("aisd.agent.sync")


class EndpointSyncService:
    def __init__(self, storage: AgentLocalStorage, server_url: Optional[str] = None):
        self.storage = storage
        self.server_url = (server_url or agent_config.server_url).rstrip("/")
        self.agent_uuid = agent_config.agent_uuid
        self.last_pending_tasks: List[Dict[str, Any]] = []

    def is_server_reachable(self) -> bool:
        """Probes the central server health endpoint."""
        try:
            with httpx.Client(timeout=3.0) as client:
                res = client.get(f"{self.server_url}/api/health")
                return res.status_code == 200
        except Exception:
            return False

    def enroll(
        self,
        ip_address: Optional[str] = None,
        adapter_name: Optional[str] = None,
        mac_address: Optional[str] = None,
        telemetry: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Registers the agent with the central server."""
        try:
            with httpx.Client(timeout=5.0) as client:
                payload: Dict[str, Any] = {
                    "agent_uuid": self.agent_uuid,
                    "hostname": agent_config.hostname,
                    "os_name": agent_config.os_name,
                    "os_version": agent_config.os_version,
                    "agent_version": agent_config.agent_version,
                }
                if ip_address:
                    payload["ip_address"] = ip_address
                if adapter_name:
                    payload["adapter_name"] = adapter_name
                if mac_address:
                    payload["mac_address"] = mac_address
                if telemetry:
                    payload["telemetry"] = telemetry

                res = client.post(f"{self.server_url}/api/agents/enroll", json=payload)
                return res.status_code == 200
        except Exception as e:
            logger.warning(f"Agent enrollment failed: {e}")
            return False

    def send_heartbeat(
        self,
        ip_address: Optional[str] = None,
        adapter_name: Optional[str] = None,
        mac_address: Optional[str] = None,
        telemetry: Optional[Dict[str, Any]] = None,
        decision_logs: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        try:
            payload: Dict[str, Any] = {"agent_uuid": self.agent_uuid, "status": "ONLINE"}
            if ip_address:
                payload["ip_address"] = ip_address
            if adapter_name:
                payload["adapter_name"] = adapter_name
            if mac_address:
                payload["mac_address"] = mac_address
            if telemetry:
                payload["telemetry"] = telemetry
            if decision_logs:
                payload["decision_logs"] = decision_logs

            with httpx.Client(timeout=5.0) as client:
                res = client.post(
                    f"{self.server_url}/api/agents/heartbeat",
                    json=payload,
                )
                if res.status_code == 200:
                    try:
                        data = res.json()
                        self.last_pending_tasks = data.get("pending_tasks", []) or []
                    except Exception:
                        self.last_pending_tasks = []
                    return True
                return False
        except Exception:
            return False

    def fetch_pending_tasks(self) -> List[Dict[str, Any]]:
        """Polls central server for newly dispatched remote execution tasks."""
        try:
            with httpx.Client(timeout=3.5) as client:
                res = client.get(f"{self.server_url}/api/agents/{self.agent_uuid}/tasks/pending")
                if res.status_code == 200:
                    return res.json().get("tasks", []) or []
        except Exception:
            pass
        return []

    def report_task_result(self, task_uuid: str, result_payload: Dict[str, Any]) -> bool:
        """Uploads execution logs, postcondition verification, and reasoning back to central server."""
        try:
            with httpx.Client(timeout=8.0) as client:
                res = client.post(
                    f"{self.server_url}/api/agents/{self.agent_uuid}/tasks/{task_uuid}/result",
                    json=result_payload,
                )
                return res.status_code == 200
        except Exception as e:
            logger.warning(f"Failed to report remote task {task_uuid}: {e}")
            return False

    def sync_outbox(self) -> Tuple[int, int]:
        """
        Batches and uploads all pending local events to the server.
        Deduplicates by event_uuid on the central server.
        Returns: (accepted_count, rejected_or_duplicate_count)
        """
        pending = self.storage.get_pending_events(limit=50)
        if not pending:
            return 0, 0

        if not self.is_server_reachable():
            logger.info("Server is unreachable. Events remain queued locally in SQLite.")
            return 0, 0

        events_payload = [
            {
                "event_uuid": ev["event_uuid"],
                "event_type": ev["event_type"],
                "payload": ev["payload"],
                "created_at_local": ev["created_at_local"],
            }
            for ev in pending
        ]

        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.post(
                    f"{self.server_url}/api/agents/{self.agent_uuid}/sync",
                    json={"agent_uuid": self.agent_uuid, "events": events_payload},
                )
                if res.status_code == 200:
                    data = res.json()
                    accepted = data.get("accepted_uuids", [])
                    duplicate = data.get("duplicate_uuids", [])
                    synced_all = accepted + duplicate

                    if synced_all:
                        self.storage.mark_events_synced(synced_all)
                    return len(accepted), len(duplicate)
                else:
                    logger.warning(f"Sync upload returned HTTP {res.status_code}: {res.text[:200]}")
                    uuids = [ev["event_uuid"] for ev in pending]
                    self.storage.increment_retries(uuids)
        except Exception as e:
            logger.warning(f"Sync batch upload error: {e}")
            uuids = [ev["event_uuid"] for ev in pending]
            self.storage.increment_retries(uuids)

        return 0, 0
