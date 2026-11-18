# AISD — Offline Endpoint Operation & Synchronization

## 1. Problem Context

In a college environment, endpoints frequently disconnect from campus Wi-Fi or experience local network subnet failures. The endpoint agent must continue local troubleshooting and incident queueing without failing.

---

## 2. Local SQLite Outbox Design

When disconnected, the agent stores events in a local SQLite database (`agent_local.db`):

```sql
CREATE TABLE outbox_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_uuid TEXT UNIQUE NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT DEFAULT 'PENDING',
    retry_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    synced_at TEXT
);
```

### Event Types:
- `INCIDENT_REPORTED`: Ticket created locally by user while offline.
- `DIAGNOSTIC_COLLECTED`: Local telemetry and deterministic rule findings.
- `ACTION_EXECUTED`: Allowlisted local repair action and verification evidence.

---

## 3. Idempotent Synchronization Protocol

```mermaid
sequenceDiagram
    participant Endpoint as Windows Endpoint Agent
    participant SQLite as Local SQLite Outbox
    participant Server as Central AISD Server
    participant DB as Central PostgreSQL / SQLite

    Endpoint->>Server: GET /api/health (Probe reachability)
    alt Server Unreachable
        Endpoint->>Endpoint: Remain in offline mode; wait next cycle
    else Server Reachable
        Endpoint->>SQLite: SELECT * FROM outbox_events WHERE status = 'PENDING'
        SQLite-->>Endpoint: Batch of events [event_uuid, payload]
        Endpoint->>Server: POST /api/agents/{uuid}/sync (Batch)
        Server->>DB: Check event_uuid uniqueness (Deduplication)
        alt UUID already processed
            Server-->>Endpoint: Mark as duplicate (Skip re-ingestion)
        else New UUID
            Server->>DB: Ingest Incident / Diagnostic / Action
            Server-->>Endpoint: Accepted event_uuids
        end
        Endpoint->>SQLite: UPDATE outbox_events SET status = 'SYNCED'
    end
```

---

## 4. Conflict Resolution & Guarantees

1. **At-Least-Once Delivery with Server Deduplication:**
   Every event is generated with a client-side UUID v4. The central server enforces a unique constraint on `sync_idempotency_key` and `endpoint_sync_events.event_uuid`.
2. **Deterministic Monotonicity:**
   Offline records do not overwrite newer server records. If a technician already triaged or resolved an incident centrally, synced offline telemetry appends to the timeline as historical evidence without rolling back the status.
