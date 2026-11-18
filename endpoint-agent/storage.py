import sqlite3
import json
import uuid
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger("aisd.agent.storage")


class AgentLocalStorage:
    def __init__(self, db_path: str = "agent_local.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Outbox table for offline synchronization
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS outbox_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_uuid TEXT UNIQUE NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT DEFAULT 'PENDING',
                    retry_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    synced_at TEXT
                )
            """)
            # Local incidents cache
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS local_incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_number TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    category TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            # Cached troubleshooting procedures (for offline operation)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cached_sops (
                    doc_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    category TEXT NOT NULL,
                    content TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            # Remediation history table for tracking cooldown and retry threshold safeguards
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS remediation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    issue_key TEXT NOT NULL,
                    tool_id TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    verification_status TEXT NOT NULL,
                    attempted_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def queue_event(self, event_type: str, payload: Dict[str, Any], event_uuid: Optional[str] = None) -> str:
        u_id = event_uuid or str(uuid.uuid4())
        now_str = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO outbox_events (event_uuid, event_type, payload, status, created_at)
                VALUES (?, ?, ?, 'PENDING', ?)
            """, (u_id, event_type, json.dumps(payload), now_str))
            conn.commit()
        return u_id

    def get_pending_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, event_uuid, event_type, payload, status, retry_count, created_at
                FROM outbox_events
                WHERE status = 'PENDING'
                ORDER BY id ASC
                LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            results = []
            for r in rows:
                results.append({
                    "id": r["id"],
                    "event_uuid": r["event_uuid"],
                    "event_type": r["event_type"],
                    "payload": json.loads(r["payload"]),
                    "created_at_local": r["created_at"]
                })
            return results

    def mark_events_synced(self, event_uuids: List[str]):
        now_str = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("""
                UPDATE outbox_events
                SET status = 'SYNCED', synced_at = ?
                WHERE event_uuid = ?
            """, [(now_str, u) for u in event_uuids])
            conn.commit()

    def increment_retries(self, event_uuids: List[str]):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("""
                UPDATE outbox_events
                SET retry_count = retry_count + 1
                WHERE event_uuid = ?
            """, [(u,) for u in event_uuids])
            conn.commit()

    def save_local_incident(self, incident_data: Dict[str, Any]):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO local_incidents (incident_number, title, description, category, priority, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                incident_data["incident_number"],
                incident_data["title"],
                incident_data["description"],
                incident_data.get("category", "NETWORK"),
                incident_data.get("priority", "MEDIUM"),
                incident_data.get("status", "NEW"),
                incident_data.get("created_at", datetime.now(timezone.utc).isoformat())
            ))
            conn.commit()

    def cache_sop(self, doc_id: str, title: str, category: str, content: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO cached_sops (doc_id, title, category, content, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (doc_id, title, category, content, datetime.now(timezone.utc).isoformat()))
            conn.commit()

    def get_cached_sops(self) -> List[Dict[str, Any]]:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT doc_id, title, category, content FROM cached_sops")
                return [dict(r) for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error fetching cached SOPs: {e}")
            return []

    def record_remediation_attempt(self, issue_key: str, tool_id: str, success: bool, verification_status: str):
        """Records a remediation execution attempt for cooldown and retry tracking."""
        try:
            now_str = datetime.now(timezone.utc).isoformat()
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO remediation_history (issue_key, tool_id, success, verification_status, attempted_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (issue_key, tool_id, 1 if success else 0, verification_status, now_str))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to record remediation attempt for {issue_key}: {e}")

    def get_recent_remediation_attempts(self, issue_key: str, within_seconds: int = 120) -> int:
        """Returns the number of remediation attempts for this issue within the specified seconds."""
        try:
            cutoff = datetime.now(timezone.utc).timestamp() - within_seconds
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT attempted_at FROM remediation_history
                    WHERE issue_key = ?
                    ORDER BY id DESC
                """, (issue_key,))
                rows = cursor.fetchall()
                count = 0
                for r in rows:
                    try:
                        dt = datetime.fromisoformat(r["attempted_at"])
                        if dt.timestamp() >= cutoff:
                            count += 1
                    except Exception:
                        pass
                return count
        except Exception as e:
            logger.error(f"Failed to check recent remediation attempts: {e}")
            return 0

    def get_failed_remediation_count(self, issue_key: str, within_seconds: Optional[int] = 900) -> int:
        """Returns consecutive failed/unresolved attempts for this issue since last success (within TTL window)."""
        try:
            cutoff = (
                datetime.now(timezone.utc).timestamp() - within_seconds
                if within_seconds is not None and within_seconds > 0
                else None
            )
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT verification_status, attempted_at FROM remediation_history
                    WHERE issue_key = ?
                    ORDER BY id DESC
                """, (issue_key,))
                rows = cursor.fetchall()
                consecutive_failures = 0
                for r in rows:
                    if cutoff is not None:
                        try:
                            if datetime.fromisoformat(r["attempted_at"]).timestamp() < cutoff:
                                break
                        except Exception:
                            pass
                    if r["verification_status"] == "resolved":
                        break
                    consecutive_failures += 1
                return consecutive_failures
        except Exception as e:
            logger.error(f"Failed to check failed remediation count: {e}")
            return 0

    def clear_remediation_history(self, issue_key: Optional[str] = None):
        """Clears remediation history, optionally for a specific issue."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if issue_key:
                    cursor.execute("DELETE FROM remediation_history WHERE issue_key = ?", (issue_key,))
                else:
                    cursor.execute("DELETE FROM remediation_history")
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to clear remediation history: {e}")
