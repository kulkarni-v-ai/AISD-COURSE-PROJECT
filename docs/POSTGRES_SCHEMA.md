# AISD Database: PostgreSQL Schema Mapping & DDL Reference

This document defines the production database schema for the **AI-based Incident Support and Diagnosis (AISD)** platform targeting **PostgreSQL 16+**.

---

## 1. SQLAlchemy to PostgreSQL Type Mapping

| SQLAlchemy Column Type | PostgreSQL 16 Equivalent | Purpose / Notes |
|:---|:---|:---|
| `Column(Integer, primary_key=True)` | `SERIAL PRIMARY KEY` / `INTEGER GENERATED ALWAYS AS IDENTITY` | Auto-incrementing identifier |
| `Column(String(N))` | `VARCHAR(N)` | Bounded variable length strings (UUIDs, status codes, short keys) |
| `Column(Text)` | `TEXT` | Unbounded text (descriptions, summaries, SOP content, logs) |
| `Column(Boolean)` | `BOOLEAN` | True/False boolean flags |
| `Column(DateTime(timezone=True))` | `TIMESTAMPTZ` | Timestamp with UTC timezone preservation |
| `Column(JSON)` | `JSONB` | Structured JSON data, findings, arguments, and embeddings |
| `ForeignKey("table.id")` | `REFERENCES table(id)` | Foreign key relational integrity constraints |

---

## 2. PostgreSQL DDL (Data Definition Language)

```sql
-- ============================================================================
-- AISD PostgreSQL Production Schema DDL
-- Database: aisd_db
-- ============================================================================

-- 1. USERS
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(32) NOT NULL DEFAULT 'student',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- 2. ENDPOINTS
CREATE TABLE IF NOT EXISTS endpoints (
    id SERIAL PRIMARY KEY,
    agent_uuid VARCHAR(64) NOT NULL UNIQUE,
    hostname VARCHAR(128) NOT NULL,
    os_name VARCHAR(64) NOT NULL DEFAULT 'Windows',
    os_version VARCHAR(64) NOT NULL,
    agent_version VARCHAR(32) NOT NULL DEFAULT '1.0.0',
    owner_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(32) NOT NULL DEFAULT 'ONLINE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_endpoints_agent_uuid ON endpoints(agent_uuid);

-- 3. INCIDENTS
CREATE TABLE IF NOT EXISTS incidents (
    id SERIAL PRIMARY KEY,
    incident_number VARCHAR(32) NOT NULL UNIQUE,
    reporter_id INTEGER NOT NULL REFERENCES users(id),
    endpoint_id INTEGER REFERENCES endpoints(id) ON DELETE SET NULL,
    assigned_technician_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    category VARCHAR(64) NOT NULL DEFAULT 'NETWORK',
    priority VARCHAR(32) NOT NULL DEFAULT 'MEDIUM',
    status VARCHAR(32) NOT NULL DEFAULT 'NEW',
    diagnosis_summary TEXT,
    resolution_summary TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMPTZ,
    sync_idempotency_key VARCHAR(64) UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_incidents_number ON incidents(incident_number);
CREATE INDEX IF NOT EXISTS idx_incidents_sync_key ON incidents(sync_idempotency_key);

-- 4. INCIDENT_COMMENTS
CREATE TABLE IF NOT EXISTS incident_comments (
    id SERIAL PRIMARY KEY,
    incident_id INTEGER NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    author_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    author_name VARCHAR(128) NOT NULL DEFAULT 'System',
    comment TEXT NOT NULL,
    is_internal INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 5. DIAGNOSTIC_RUNS
CREATE TABLE IF NOT EXISTS diagnostic_runs (
    id SERIAL PRIMARY KEY,
    incident_id INTEGER NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    endpoint_id INTEGER REFERENCES endpoints(id) ON DELETE SET NULL,
    source VARCHAR(32) NOT NULL DEFAULT 'RULE',
    rule_version VARCHAR(32),
    model_name VARCHAR(64),
    status VARCHAR(32) NOT NULL DEFAULT 'COMPLETED',
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    summary TEXT,
    findings_json JSONB
);

-- 6. DIAGNOSTIC_EVIDENCE
CREATE TABLE IF NOT EXISTS diagnostic_evidence (
    id SERIAL PRIMARY KEY,
    diagnostic_run_id INTEGER NOT NULL REFERENCES diagnostic_runs(id) ON DELETE CASCADE,
    evidence_type VARCHAR(64) NOT NULL,
    key VARCHAR(128) NOT NULL,
    value_json JSONB NOT NULL,
    collected_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sensitivity VARCHAR(32) NOT NULL DEFAULT 'LOW',
    redacted INTEGER NOT NULL DEFAULT 0
);

-- 7. KNOWLEDGE_DOCUMENTS
CREATE TABLE IF NOT EXISTS knowledge_documents (
    id SERIAL PRIMARY KEY,
    doc_id VARCHAR(64) NOT NULL UNIQUE,
    title VARCHAR(255) NOT NULL,
    source_type VARCHAR(64) NOT NULL DEFAULT 'SOP',
    category VARCHAR(64) NOT NULL DEFAULT 'NETWORK',
    version VARCHAR(32) NOT NULL DEFAULT '1.0',
    approved BOOLEAN NOT NULL DEFAULT TRUE,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_knowledge_docs_doc_id ON knowledge_documents(doc_id);

-- 8. KNOWLEDGE_CHUNKS
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding_json JSONB,
    metadata_json JSONB
);

-- 9. REMEDIATION_PLANS
CREATE TABLE IF NOT EXISTS remediation_plans (
    id SERIAL PRIMARY KEY,
    incident_id INTEGER NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    diagnostic_run_id INTEGER REFERENCES diagnostic_runs(id) ON DELETE SET NULL,
    tool_id VARCHAR(64) NOT NULL,
    arguments_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason TEXT NOT NULL,
    risk_level VARCHAR(16) NOT NULL DEFAULT 'R1',
    approval_required INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 10. APPROVALS
CREATE TABLE IF NOT EXISTS approvals (
    id SERIAL PRIMARY KEY,
    remediation_plan_id INTEGER NOT NULL REFERENCES remediation_plans(id) ON DELETE CASCADE,
    approver_user_id INTEGER NOT NULL REFERENCES users(id),
    decision VARCHAR(32) NOT NULL,
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_approvals_plan UNIQUE (remediation_plan_id)
);

-- 11. REMEDIATION_EXECUTIONS
CREATE TABLE IF NOT EXISTS remediation_executions (
    id SERIAL PRIMARY KEY,
    remediation_plan_id INTEGER NOT NULL REFERENCES remediation_plans(id) ON DELETE CASCADE,
    endpoint_id INTEGER REFERENCES endpoints(id) ON DELETE SET NULL,
    tool_id VARCHAR(64) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    execution_status VARCHAR(32) NOT NULL DEFAULT 'RUNNING',
    exit_code INTEGER,
    output_redacted TEXT,
    error_redacted TEXT,
    is_mock INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT uq_executions_plan UNIQUE (remediation_plan_id)
);

-- 12. VERIFICATION_RESULTS
CREATE TABLE IF NOT EXISTS verification_results (
    id SERIAL PRIMARY KEY,
    execution_id INTEGER NOT NULL REFERENCES remediation_executions(id) ON DELETE CASCADE,
    verification_type VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    evidence_json JSONB,
    verified_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_verification_execution UNIQUE (execution_id)
);

-- 13. ENDPOINT_SYNC_EVENTS
CREATE TABLE IF NOT EXISTS endpoint_sync_events (
    id SERIAL PRIMARY KEY,
    endpoint_id INTEGER NOT NULL REFERENCES endpoints(id) ON DELETE CASCADE,
    event_uuid VARCHAR(64) NOT NULL UNIQUE,
    event_type VARCHAR(64) NOT NULL,
    payload_json JSONB NOT NULL,
    created_at_local TIMESTAMPTZ NOT NULL,
    received_at_server TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sync_status VARCHAR(32) NOT NULL DEFAULT 'ACCEPTED'
);
CREATE INDEX IF NOT EXISTS idx_sync_events_uuid ON endpoint_sync_events(event_uuid);

-- 14. AUDIT_EVENTS
CREATE TABLE IF NOT EXISTS audit_events (
    id SERIAL PRIMARY KEY,
    actor_type VARCHAR(32) NOT NULL DEFAULT 'SYSTEM',
    actor_id VARCHAR(64),
    event_type VARCHAR(64) NOT NULL,
    entity_type VARCHAR(32) NOT NULL,
    entity_id VARCHAR(64) NOT NULL,
    details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```
