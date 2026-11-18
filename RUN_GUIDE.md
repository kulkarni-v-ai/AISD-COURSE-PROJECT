# AISD — Complete Team Member Run Guide

Welcome to the **AISD (AI-Powered IT Incident Management System)** project!
This guide is written specifically so any team member can set up and run the entire application on their Windows laptop in less than 3 minutes.

---

## ⚡ Method 1: The Easiest Way (1-Click Automated Setup)

1. **Unzip the downloaded `AISD_PROJECT.zip`** to any folder on your computer (e.g. `C:\Projects\AISD` or `Desktop\AISD`).
2. Double-click the file named **`SETUP_AND_RUN.bat`**.
3. The script will:
   - Check your Python and Node.js versions.
   - Automatically install all backend dependencies (`pip install ...`).
   - Automatically install all frontend dependencies (`npm install`).
   - Start the FastAPI Backend on port `8000`.
   - Start the Next.js Frontend on port `3000`.
   - Automatically open your browser to `http://localhost:3000`!

*(On subsequent runs after initial setup, simply double-click **`RUN_AISD.bat`** to start instantly!)*

---

## 🛠️ Method 2: Manual Terminal Setup (Step-by-Step)

If you prefer running commands in PowerShell or Command Prompt:

### 1. Prerequisites
- **Python 3.10+**: Download from [python.org](https://www.python.org/downloads/) *(Remember to check "Add Python to PATH")*.
- **Node.js 18+**: Download from [nodejs.org](https://nodejs.org/) *(LTS version recommended)*.
- *(Optional)* **Ollama**: If you want local LLM inference. If Ollama is not installed or not running, AISD automatically falls back to deterministic diagnostic rules so the system works 100% offline!

### 2. Install Backend Dependencies
Open PowerShell or Command Prompt:
```powershell
cd aisd\backend
python -m pip install -r requirements.txt greenlet
```

### 3. Install Frontend Dependencies
```powershell
cd ..\frontend
npm install
```

### 4. Start the Application
Open **two** terminal windows:

**Terminal 1 (Backend):**
```powershell
cd aisd\backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 (Frontend):**
```powershell
cd aisd\frontend
npm run dev
```

Now open your web browser at:
👉 **`http://localhost:3000`**

---

## 🔑 Login Credentials

The database auto-seeds on first startup with these test accounts:

| Role | Email | Password | What You Can Do |
|---|---|---|---|
| **Technician** | `tech@college.edu` | `Tech@123` | View all incidents, trigger AI diagnosis, approve/reject plans, execute repairs, verify outcomes. |
| **Student** | `student@college.edu` | `Student@123` | Report new incidents, track personal ticket status, view resolution summaries. |
| **Administrator** | `admin@college.edu` | `Admin@123` | Full access, manage knowledge base SOPs, system audit logs, and endpoint fleet. |

*(On the login screen `http://localhost:3000/login`, you can also click the quick demo buttons to log in with 1 click!)*

---

## 🎯 How to Demonstrate the Wi-Fi Incident Workflow

1. Sign in as **Technician** (`tech@college.edu` / `Tech@123`).
2. Go to **Incidents** page and click ticket **INC-20261104-1001**:
   *"My laptop is connected to the college Wi-Fi, but I cannot access anything."*
3. Click the blue **"Run Ollama Diagnosis"** button (or **"Run Rules Only"**).
   - Notice how it identifies the link-local **APIPA `169.254.88.192`** address and missing gateway with **95% confidence**.
   - Notice the RAG section citing **`KB-NET-001`** (College Wi-Fi SOP).
4. Click **"Propose Tool: renew_dhcp"**.
   - Notice the system flags this as **Risk Level R2**, requiring technician authorization.
5. Click **"Authorize / Approve"**.
6. Click **"Execute Remediation & Verify Postcondition"**.
   - Notice the agent executes the repair.
   - The verification engine checks postconditions: confirms valid IP (`10.12.4.152`) and gateway ping (`3.8 ms`).
   - The ticket status automatically transitions to **`RESOLVED`**!

---

## 💻 1-Click Automated Demo Script

You can also run the entire 12-step scenario directly in the terminal to show your professors/evaluators:
```powershell
python aisd\scripts\run_demo.py
```

---

## 📡 Running the Windows Endpoint Agent (Offline Mode)

On any managed computer, run the lightweight endpoint agent:
```powershell
cd aisd\endpoint-agent

# 1. Check agent identity and connection status
python agent.py status

# 2. Run local diagnostic telemetry collection
python agent.py diagnose

# 3. Evaluate local deterministic rules (works completely offline with NO GPU!)
python agent.py evaluate

# 4. Report an offline ticket (saved in local SQLite outbox)
python agent.py report --title "Lab printer offline" --desc "Paper jam"

# 5. Sync queued events to central server when back online
python agent.py sync
```

---

## ❓ Frequently Asked Questions (Troubleshooting)

**Q: `python` or `npm` is not recognized as an internal or external command.**  
A: You need to install Python or Node.js and ensure you checked *"Add to PATH"* during installation. Restart your terminal after installing.

**Q: Does my laptop need a GPU or Ollama to run this?**  
A: **No.** Endpoint agents and the central server run on standard CPU. If Ollama is not running, AISD automatically falls back to its deterministic rule engine and RAG pipeline.

**Q: Where is data stored?**  
A: By default, it uses SQLite (`aisd.db` for the server, `agent_local.db` for the endpoint agent) so there is **zero database setup** required. PostgreSQL + Docker Compose is also provided in `infra/` for server deployment.
