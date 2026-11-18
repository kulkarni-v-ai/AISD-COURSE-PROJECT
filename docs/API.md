# AISD — REST API Specification

Central Server Base URL: `http://127.0.0.1:8000/api`  
Interactive OpenAPI Documentation: `http://127.0.0.1:8000/docs`

---

## 1. Authentication & RBAC

| Method | Endpoint | Description | Role Required |
|---|---|---|---|
| `POST` | `/api/auth/login` | User login, returns JWT access token | Public |
| `POST` | `/api/auth/register` | Register new user account | Public |
| `GET` | `/api/auth/me` | Fetch authenticated profile | Any authenticated |

---

## 2. Incidents Management

| Method | Endpoint | Description | Role Required |
|---|---|---|---|
| `POST` | `/api/incidents` | Create a new incident ticket | Student, Faculty, Tech, Admin |
| `GET` | `/api/incidents` | List incidents (students see own; techs see all) | Any authenticated |
| `GET` | `/api/incidents/{id}` | Get incident details | Any authenticated |
| `PATCH`| `/api/incidents/{id}` | Update incident fields | Tech, Admin |
| `POST` | `/api/incidents/{id}/assign` | Assign technician to ticket | Tech, Admin |
| `POST` | `/api/incidents/{id}/status` | Validated status transition | Tech, Admin |
| `POST` | `/api/incidents/{id}/escalate` | Escalate incident to L2 | Tech, Admin |
| `POST` | `/api/incidents/{id}/comments` | Add comment or internal technician note | Any authenticated |

---

## 3. Automated Diagnostics

| Method | Endpoint | Description | Role Required |
|---|---|---|---|
| `POST` | `/api/incidents/{id}/diagnose` | Run deterministic rules + Ollama AI reasoning + RAG search | Any authenticated |
| `GET` | `/api/incidents/{id}/diagnostics`| Retrieve all diagnostic runs and discrete evidence | Any authenticated |

---

## 4. Remediation & Verification

| Method | Endpoint | Description | Role Required |
|---|---|---|---|
| `POST` | `/api/incidents/{id}/remediation-plan` | Propose tool execution plan; policy checks risk | Tech, Admin |
| `POST` | `/api/remediation-plans/{id}/approve` | Approve or reject a plan requiring authorization | Tech, Admin |
| `POST` | `/api/remediation-plans/{id}/execute` | Execute action and trigger postcondition verification | Tech, Admin |
| `GET` | `/api/remediation-plans/{id}/verification`| Fetch postcondition verification results | Any authenticated |

---

## 5. Knowledge Base & RAG

| Method | Endpoint | Description | Role Required |
|---|---|---|---|
| `GET` | `/api/knowledge/documents` | List approved troubleshooting SOPs | Any authenticated |
| `POST` | `/api/knowledge/documents` | Ingest and chunk new approved SOP | Tech, Admin |
| `GET` | `/api/knowledge/search` | Search knowledge base chunks by semantic similarity | Any authenticated |

---

## 6. Endpoint Agents

| Method | Endpoint | Description | Role Required |
|---|---|---|---|
| `POST` | `/api/agents/enroll` | Register or refresh Windows endpoint | Agent |
| `POST` | `/api/agents/heartbeat` | Agent keep-alive pulse | Agent |
| `GET` | `/api/agents` | List active fleet computers | Tech, Admin |
| `POST` | `/api/agents/{agent_uuid}/sync` | Idempotent batch upload of offline queued events | Agent |

---

## 7. Metrics & Dashboard

| Method | Endpoint | Description | Role Required |
|---|---|---|---|
| `GET` | `/api/dashboard/stats` | Live KPI metrics, category/priority counts, audit logs | Any authenticated |
| `GET` | `/api/health` | Health check probe | Public |
