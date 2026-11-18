# AISD — Step-by-Step Evaluator Demonstration Script

Follow this script to demonstrate the complete incident lifecycle for tomorrow's presentation.

---

## 1. Prerequisites Check

1. Central backend running at `http://127.0.0.1:8000` (FastAPI).
2. Next.js web portal running at `http://localhost:3000`.
3. (Optional) Ollama running locally with `qwen3.5:4b` and `nomic-embed-text:latest`. If Ollama is stopped, AISD demonstrates automatic fallback to deterministic rules.

---

## 2. Interactive Web Portal Walkthrough

### Step 1: Sign in as Technician
- Open `http://localhost:3000/login`.
- Click the **Technician** quick button (`tech@college.edu` / `Tech@123`).
- Click **Sign In**.
- You are directed to the **IT Operations Dashboard**.

### Step 2: Review Overview Metrics
- Inspect the live KPI cards: Total Tickets, In Progress, Verified Resolved, and Active Endpoints.
- View the **Real-Time Audit & Event Log** displaying all system events.

### Step 3: Open the Target Demonstration Incident
- Click **Incidents** in the navigation bar.
- Click ticket **INC-20261104-1001**:
  - Title: *"My laptop is connected to the college Wi-Fi, but I cannot access anything."*
  - Priority: `HIGH` &bull; Category: `NETWORK` &bull; Status: `NEW`.

### Step 4: Run AI & Deterministic Diagnosis
- On the Incident Console, click the **Run Ollama Diagnosis** button (or **Run Rules Only**).
- Observe the diagnostic output:
  - **Summary:** Identifies APIPA `169.254.88.192` address and missing default gateway.
  - **Confidence:** 95% confidence on DHCP lease acquisition failure.
  - **Grounded Evidence:** Cites `ip_config`, `gateway_ping`, and `event_log`.
  - **RAG Citations:** Cites `KB-NET-001` (College Wi-Fi & DHCP Lease Failure Recovery SOP).
  - **Proposed Action:** Recommends registered tool `renew_dhcp`.

### Step 5: Propose Remediation Plan
- Click **Propose Tool: renew_dhcp**.
- A new Remediation Plan is created:
  - Tool ID: `renew_dhcp`.
  - Risk Level: `R2` (Disruptive / Reversible).
  - Approval Required: `Yes` (Gated by safety policy).
  - Incident status moves to `APPROVAL_REQUIRED`.

### Step 6: Technician Authorization
- Click the green **Authorize / Approve** button.
- The plan status transitions to `APPROVED` and incident moves to `ACTION_PLANNED`.

### Step 7: Execute Remediation & Postcondition Verification
- Click **Execute Remediation & Verify Postcondition**.
- The agent executes the tool in Mock Mode.
- Output log shows:
  - Releasing adapter lease...
  - Negotiating DHCP with campus controller...
  - Assigned: `10.12.4.152`, Gateway: `10.12.0.1`.
- Postcondition verification runs:
  - Status: `VERIFIED_RESOLVED`.
  - Ping latency: `3.8 ms`.
- Incident automatically updates to `RESOLVED`!
- Verified resolution summary is written into the ticket.

---

## 3. Automated Console Script

Alternatively, you can run the demonstration completely automated from terminal:

```powershell
python aisd\scripts\run_demo.py
```

This runs the exact 12-step sequence with formatted banners in under 5 seconds!

---

## 4. Offline Endpoint Demonstration

To demonstrate offline behavior:
```powershell
# 1. Stop backend or disconnect network
# 2. Open terminal in endpoint-agent
cd aisd\endpoint-agent

# 3. Inspect offline agent status
python agent.py status

# 4. Run local diagnostic evaluation (without server or GPU!)
python agent.py evaluate

# 5. Report an offline ticket (saved to local SQLite outbox)
python agent.py report --title "Library printer offline" --desc "Paper jam in Tray 2"

# 6. Verify event is queued in SQLite
python agent.py status

# 7. Start backend, then trigger sync
python agent.py sync
```
Events are idempotently ingested into the central server with zero duplication!
