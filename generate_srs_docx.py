import os
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn

def create_element(name):
    return OxmlElement(name)

def set_cell_background(cell, fill_hex):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    tcPr.append(shd)

def set_cell_margins(cell, top=100, bottom=100, left=150, right=150):
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = parse_xml(f'<w:tcMar {nsdecls("w")}><w:top w:w="{top}" w:type="dxa"/><w:bottom w:w="{bottom}" w:type="dxa"/><w:left w:w="{left}" w:type="dxa"/><w:right w:w="{right}" w:type="dxa"/></w:tcMar>')
    tcPr.append(tcMar)

def set_table_borders(table, color="D3D3D3"):
    tblPr = table._tbl.tblPr
    borders = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        f'<w:top w:val="single" w:sz="4" w:space="0" w:color="{color}"/>'
        f'<w:bottom w:val="single" w:sz="4" w:space="0" w:color="{color}"/>'
        f'<w:left w:val="none"/>'
        f'<w:right w:val="none"/>'
        f'<w:insideH w:val="single" w:sz="4" w:space="0" w:color="{color}"/>'
        f'<w:insideV w:val="none"/>'
        f'</w:tblBorders>'
    )
    tblPr.append(borders)

def build_srs_doc(output_path):
    doc = docx.Document()

    # Page Margins
    for section in doc.sections:
        section.top_margin = Inches(1.0)
        section.bottom_margin = Inches(1.0)
        section.left_margin = Inches(1.0)
        section.right_margin = Inches(1.0)

    # Styles Setup
    styles = doc.styles
    normal_style = styles['Normal']
    normal_font = normal_style.font
    normal_font.name = 'Calibri'
    normal_font.size = Pt(11)
    normal_font.color.rgb = RGBColor(0x22, 0x22, 0x22)

    # ------------------ COVER / TITLE PAGE ------------------
    p_title_space = doc.add_paragraph()
    p_title_space.paragraph_format.space_before = Pt(36)

    title_p = doc.add_paragraph()
    title_run = title_p.add_run("Software Requirements Specification (SRS)")
    title_run.font.name = 'Calibri'
    title_run.font.size = Pt(26)
    title_run.font.bold = True
    title_run.font.color.rgb = RGBColor(0x02, 0x84, 0xC7) # Sky-600
    title_p.paragraph_format.space_after = Pt(4)

    subtitle_p = doc.add_paragraph()
    sub_run = subtitle_p.add_run("Autonomous Intelligent Service Desk (AISD)\nHybrid Edge-Cloud Automated Incident Management & IT Remediation System")
    sub_run.font.name = 'Calibri'
    sub_run.font.size = Pt(15)
    sub_run.font.color.rgb = RGBColor(0x47, 0x55, 0x69) # Slate-600
    subtitle_p.paragraph_format.space_after = Pt(28)

    # Meta Table
    meta_table = doc.add_table(rows=5, cols=2)
    meta_table.alignment = WD_TABLE_ALIGNMENT.LEFT
    meta_data = [
        ("Project:", "Autonomous Intelligent Service Desk (AISD)"),
        ("Compliance Standard:", "IEEE Std 830-1998 / ISO/IEC/IEEE 29148:2018"),
        ("Version & Status:", "1.0 - Production Specification"),
        ("Core AI Model:", "Meta Llama 8B Parameter Model (llama3.1:8b)"),
        ("Target Subsystems:", "FastAPI, PostgreSQL 16, Next.js 15, Windows 10/11 Endpoint Agent")
    ]
    for i, (k, v) in enumerate(meta_data):
        row = meta_table.rows[i]
        c0, c1 = row.cells[0], row.cells[1]
        c0.width = Inches(2.2)
        c1.width = Inches(4.3)
        r0 = c0.paragraphs[0].add_run(k)
        r0.bold = True
        r0.font.color.rgb = RGBColor(0x1E, 0x29, 0x3B)
        r1 = c1.paragraphs[0].add_run(v)
        r1.font.color.rgb = RGBColor(0x33, 0x41, 0x55)
        set_cell_background(c0, "F8FAFC")
        set_cell_background(c1, "F8FAFC")
        set_cell_margins(c0, 80, 80, 100, 100)
        set_cell_margins(c1, 80, 80, 100, 100)

    set_table_borders(meta_table, "CBD5E1")
    doc.add_page_break()

    # Helper function for Section Headings
    def add_h1(text):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(18)
        p.paragraph_format.space_after = Pt(6)
        p.paragraph_format.keep_with_next = True
        run = p.add_run(text)
        run.font.name = 'Calibri'
        run.font.size = Pt(18)
        run.font.bold = True
        run.font.color.rgb = RGBColor(0x0F, 0x17, 0x2A) # Slate-900
        return p

    def add_h2(text):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(14)
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.keep_with_next = True
        run = p.add_run(text)
        run.font.name = 'Calibri'
        run.font.size = Pt(14)
        run.font.bold = True
        run.font.color.rgb = RGBColor(0x02, 0x84, 0xC7) # Sky-600
        return p

    def add_h3(text):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(10)
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.keep_with_next = True
        run = p.add_run(text)
        run.font.name = 'Calibri'
        run.font.size = Pt(12)
        run.font.bold = True
        run.font.color.rgb = RGBColor(0x33, 0x41, 0x55)
        return p

    def add_p(text, bold_prefix=None, space_after=6):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(space_after)
        p.paragraph_format.line_spacing = 1.15
        if bold_prefix:
            r_pre = p.add_run(bold_prefix)
            r_pre.bold = True
            r_pre.font.color.rgb = RGBColor(0x0F, 0x17, 0x2A)
        r_text = p.add_run(text)
        r_text.font.color.rgb = RGBColor(0x33, 0x41, 0x55)
        return p

    def add_bullet(text, bold_prefix=None):
        p = doc.add_paragraph(style='List Bullet')
        p.paragraph_format.space_after = Pt(3)
        p.paragraph_format.line_spacing = 1.15
        if bold_prefix:
            r_pre = p.add_run(bold_prefix)
            r_pre.bold = True
            r_pre.font.color.rgb = RGBColor(0x0F, 0x17, 0x2A)
        r_text = p.add_run(text)
        r_text.font.color.rgb = RGBColor(0x33, 0x41, 0x55)
        return p

    def create_styled_table(headers, data, col_widths=None):
        t = doc.add_table(rows=len(data) + 1, cols=len(headers))
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        set_table_borders(t, "CBD5E1")

        # Header
        hdr_row = t.rows[0]
        for col_idx, text in enumerate(headers):
            cell = hdr_row.cells[col_idx]
            if col_widths and col_idx < len(col_widths):
                cell.width = Inches(col_widths[col_idx])
            set_cell_background(cell, "0284C7") # Sky-600
            set_cell_margins(cell, 120, 120, 120, 120)
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            r = p.add_run(text)
            r.bold = True
            r.font.size = Pt(10)
            r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

        # Rows
        for r_idx, row_vals in enumerate(data):
            row = t.rows[r_idx + 1]
            bg_hex = "F8FAFC" if (r_idx % 2 == 1) else "FFFFFF"
            for c_idx, val in enumerate(row_vals):
                cell = row.cells[c_idx]
                if col_widths and c_idx < len(col_widths):
                    cell.width = Inches(col_widths[c_idx])
                set_cell_background(cell, bg_hex)
                set_cell_margins(cell, 100, 100, 100, 100)
                p = cell.paragraphs[0]
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                r = p.add_run(str(val))
                r.font.size = Pt(9.5)
                r.font.color.rgb = RGBColor(0x33, 0x41, 0x55)
        doc.add_paragraph().paragraph_format.space_after = Pt(6)
        return t

    # ==================== 1. INTRODUCTION ====================
    add_h1("1. Introduction")
    add_h2("1.1 Purpose")
    add_p("This Software Requirements Specification (SRS) defines the functional, non-functional, interface, safety, and architectural requirements for the Autonomous Intelligent Service Desk (AISD). AISD is an enterprise- and campus-grade IT incident management platform that pairs a centralized AI-orchestrated diagnostic backend with resilient local Windows endpoint agents.")
    add_p("The document serves as the formal baseline for developers, system architects, IT support technicians, QA engineers, and operations managers throughout the lifecycle of the system.")

    add_h2("1.2 Document Conventions")
    add_p("This document complies with IEEE Std 830-1998 and ISO/IEC/IEEE 29148:2018 standards.")
    add_bullet(" Mandatory capability required for system operation and release.", bold_prefix="[P1 - Mandatory]:")
    add_bullet(" Important operational capability supporting standard operating procedures.", bold_prefix="[P2 - Highly Desirable]:")
    add_bullet(" Enhancement feature providing supplementary productivity.", bold_prefix="[P3 - Optional]:")
    add_bullet(" Telemetry collection, queries, and passive probing with zero system impact.", bold_prefix="[R0 - Read-Only]:")
    add_bullet(" Automated safe operational routines (e.g., DNS resolver cache flushes).", bold_prefix="[R1 - Low Impact]:")
    add_bullet(" Reversible network or service changes gated strictly by Human-in-the-Loop (HITL) technician approval.", bold_prefix="[R2 - Disruptive / Reversible]:")
    add_bullet(" Elevated administrative changes (driver resets, persistent alterations).", bold_prefix="[R3 - High Risk]:")

    add_h2("1.3 Intended Audience and Reading Suggestions")
    add_bullet(" Focus on Section 2 (Overall Description), Section 4 (Features & 10 Failure Scenarios), and Section 4.3 (Use Cases).", bold_prefix="Technicians and Support Personnel:")
    add_bullet(" Review Section 2.1 (Product Perspective), Section 3 (External Interfaces), Section 4.2 (Stimulus/Response), and Section 5.1 (Performance).", bold_prefix="Backend & AI Engineers:")
    add_bullet(" Focus on Section 2.1, Section 3.2 (Hardware Interfaces), Section 4.2 (Static IP/DNS Remediation), and Appendix C (Traceability).", bold_prefix="Endpoint Agent Engineers:")
    add_bullet(" Review Section 5.2 (Safety Requirements), Section 5.3 (Security Requirements), and Section 5.5 (Business Rules).", bold_prefix="Security & Audit Officers:")

    add_h2("1.4 Product Scope")
    add_p("The AISD system resolves recurring IT helpdesk bottlenecks by automating client endpoint diagnostics and self-healing operations while preserving enterprise security boundaries:")
    add_bullet(" High-concurrency FastAPI application running over PostgreSQL managing incident lifecycles, user identity (RBAC), approval gates, diagnostic runs, immutable audit logs, and Retrieval-Augmented Generation (RAG) knowledge retrieval.", bold_prefix="Central Management Core:")
    add_bullet(" Powered by a local Meta Llama 8B parameter model (llama3.1:8b) hosted via Ollama, paired with vector embeddings (nomic-embed-text) over IT Standard Operating Procedures (SOPs). Includes automatic fallback to an expert deterministic rules engine.", bold_prefix="Central AI Diagnostic Engine:")
    add_bullet(" Standalone Python daemon deployed to Windows endpoints monitoring 10 critical network failure conditions, performing allowlisted remediation (including dynamic conversion of static IP and manual DNS to DHCP with elevation handling), verifying real operating system postconditions, and maintaining an offline SQLite outbox for guaranteed synchronization.", bold_prefix="Autonomous Windows Endpoint Agent:")

    add_h2("1.5 Definitions, Acronyms, and Abbreviations")
    glossary_data = [
        ("AISD", "Autonomous Intelligent Service Desk"),
        ("APIPA", "Automatic Private IP Addressing (169.254.0.0/16), assigned by Windows when DHCP fails"),
        ("CIM / WMI", "Common Information Model / Windows Management Instrumentation"),
        ("DHCP", "Dynamic Host Configuration Protocol"),
        ("DNS", "Domain Name System"),
        ("HITL", "Human-in-the-Loop (mandatory technician review gate for R2/R3 actions)"),
        ("JWT", "JSON Web Token (RFC 7519)"),
        ("LLM", "Large Language Model (specifically llama3.1:8b)"),
        ("Ollama", "High-performance open-source local LLM runner"),
        ("RAG", "Retrieval-Augmented Generation (semantic vector search over IT SOPs)"),
        ("RBAC", "Role-Based Access Control (student, faculty, technician, admin)"),
        ("RTM", "Requirements Traceability Matrix"),
        ("SOP", "Standard Operating Procedure"),
        ("UAC", "User Account Control (Windows security elevation prompt)")
    ]
    create_styled_table(["Term / Acronym", "Definition"], glossary_data, [2.0, 4.5])

    # ==================== 2. OVERALL DESCRIPTION ====================
    add_h1("2. Overall Description")
    add_h2("2.1 Product Perspective")
    add_p("AISD operates as a distributed client-server ecosystem designed for educational, enterprise, and corporate networks. It comprises a centralized FastAPI backend and lightweight local Windows endpoint agents.")
    add_p("Online Mode: When central network connectivity is functional, the local agent streams telemetry to the central backend. The central server indexes the event, runs RAG-grounded diagnosis using llama3.1:8b, generates remediation plans, and surfaces them on the web console.")
    add_p("Offline Mode: If network connectivity is broken (e.g., WAN outage, gateway loss, APIPA, disconnected cable), the endpoint agent operates autonomously: it executes local deterministic rules, performs pre-approved safe remediation (e.g., restoring static IP/DNS to DHCP, clearing caches), verifies postconditions, and queues all events in its SQLite outbox. Once network connectivity is restored, the agent synchronizes queued events with the central PostgreSQL database.")

    add_h2("2.2 Product Functions")
    add_bullet(" Incident submission portal with priority calculation and category triage.", bold_prefix="Self-Service Portal:")
    add_bullet(" Fast, zero-hallucination deterministic rules combined with Llama 8B parameter reasoning grounded in IT SOPs.", bold_prefix="Hybrid Diagnostic Engine:")
    add_bullet(" Detection and remediation routines for Adapter Down, Cable Disconnected, APIPA, Gateway Loss, DNS Failure, WAN Outage, Firewall Blocks, Multiple Adapters, High Latency/Loss, and Stopped Services.", bold_prefix="10 Windows Network Failures:")
    add_bullet(" Gated execution of allowlisted tools (renew_dhcp, flush_dns_cache, restart_approved_service, enable_adapter).", bold_prefix="Autonomous & HITL Remediation:")
    add_bullet(" Dynamic detection of active physical adapters (e.g., Wi-Fi 2) and automated conversion of static IP and manual DNS configurations to DHCP via netsh with UAC elevation support.", bold_prefix="Static IP / DNS to DHCP Remediation:")
    add_bullet(" Verifies operating system state (DHCP enabled, valid non-APIPA IP, reachable gateway, operational DNS). Verified issues are marked [FIXED]. Failed or un-elevated attempts are explicitly marked [FLAGGED: CANNOT BE DONE AUTOMATICALLY].", bold_prefix="Real Postcondition Verification:")
    add_bullet(" Idempotent SQLite buffering ensuring zero telemetry loss during complete network blackouts.", bold_prefix="Offline Event Outbox:")
    add_bullet(" Append-only audit logging recording all diagnostic runs, approvals, and remediation actions.", bold_prefix="Immutable Audit Trail:")

    add_h2("2.3 User Classes and Characteristics")
    user_classes = [
        ("Student / Faculty", "Basic", "student, faculty", "Submits tickets, tracks resolution, views incident status. Prohibited from executing R2/R3 actions."),
        ("Technician (L1/L2)", "Advanced", "technician", "Reviews AI diagnoses, approves/rejects R2 remediation plans, triggers manual executions, manages escalations."),
        ("IT Administrator", "Expert", "admin", "Full system governance: user management, policy modifications, R3 approvals, KB document maintenance."),
        ("Endpoint Agent", "Automated Daemon", "agent", "Collects telemetry, executes local R1 fixes, buffers offline events in SQLite, syncs with central server.")
    ]
    create_styled_table(["User Class", "Expertise", "Role Claim", "Key Responsibilities"], user_classes, [1.5, 1.0, 1.3, 2.7])

    add_h2("2.4 Operating Environment")
    add_bullet(" Windows 10/11, Windows Server 2019/2022, or Linux (Ubuntu 22.04 LTS+). Python 3.11+ / 3.14 (AsyncIO, FastAPI, Uvicorn). PostgreSQL 16 database. Ollama local LLM server hosting llama3.1:8b.", bold_prefix="Server Infrastructure:")
    add_bullet(" Windows 10 (Build 19041+) or Windows 11 (64-bit). PowerShell 5.1+, WMI/CIM, native netsh and ipconfig. UAC elevation (RunAs / sudo) requested only for interface reconfiguration.", bold_prefix="Client Endpoints:")
    add_bullet(" Modern web browsers: Google Chrome 110+, Microsoft Edge 110+, Mozilla Firefox 110+, Safari 16+.", bold_prefix="Web Console:")

    add_h2("2.5 Design and Implementation Constraints")
    add_bullet(" Live diagnostics, network adjustments, and verifications must execute against real Windows subsystems; mock mode is strictly limited to isolated automated test suites.", bold_prefix="Zero Mock Invariant:")
    add_bullet(" Diagnostic reasoning must run locally on campus hardware via Ollama (llama3.1:8b) to prevent user/network telemetry leakage to external clouds.", bold_prefix="Local AI Execution:")
    add_bullet(" The server and agent shall only execute predefined, allowlisted commands. Arbitrary command injection is strictly prohibited.", bold_prefix="Strict Allowlist Enforcement:")
    add_bullet(" The agent daemon shall not run continuously as NT AUTHORITY\\SYSTEM to minimize attack surface; privilege elevation is requested per approved action using Windows RunAs or sudo.exe.", bold_prefix="Privilege Isolation:")

    add_h2("2.6 User Documentation")
    add_bullet(" Comprehensive guide detailing PostgreSQL initialization, Ollama model setup, and .env configuration.", bold_prefix="Administrator Guide:")
    add_bullet(" Instructions for background service deployment, task scheduler configuration, and offline sync testing.", bold_prefix="Endpoint Agent Manual:")
    add_bullet(" Standard operating procedures for interpreting AI diagnostic hypotheses and executing HITL approvals.", bold_prefix="Technician Operations Manual:")

    add_h2("2.7 Assumptions and Dependencies")
    add_bullet(" Client endpoints are equipped with PowerShell 5.1 or later.", bold_prefix="PowerShell Availability:")
    add_bullet(" Campus DHCP servers and network gateways operate standard IPv4 routing protocols.", bold_prefix="Network Services:")
    add_bullet(" For AI reasoning, Ollama is operational with llama3.1:8b; if offline, system seamlessly uses expert deterministic rules.", bold_prefix="AI Availability:")

    # ==================== 3. EXTERNAL INTERFACE REQUIREMENTS ====================
    add_h1("3. External Interface Requirements")
    add_h2("3.1 User Interfaces (UI)")
    add_p("The web console is built using Next.js 15 App Router, Tailwind CSS, and Lucide React icons:")
    add_bullet(" Summary metrics (Total Incidents, Action Planned, Resolving, Escalated), severity filtering, and real-time status tables.", bold_prefix="Dashboard (/dashboard):")
    add_bullet(" Diagnostic panel with 'Run Rules Only' and 'Run Ollama Diagnosis' triggers; live diagnostic hypothesis cards citing KB documents.", bold_prefix="Diagnostic View (/incidents/[id]):")
    add_bullet(" Plan review cards displaying tool ID, arguments, risk rating, and HITL Approve/Reject buttons.", bold_prefix="Remediation Panel:")
    add_bullet(" Displays real-time stdout, stderr, exit code, and verification results. Prominently shows green '[FIXED]' banner or red '[FLAGGED: CANNOT BE DONE AUTOMATICALLY]' banner.", bold_prefix="Verification & Execution Console:")

    add_h2("3.2 Hardware Interfaces")
    add_bullet(" Wi-Fi 802.11a/b/g/n/ac/ax wireless network cards (e.g., Realtek RTL8852BE, Intel AX200). Realtek PCIe GbE Family Controllers and Gigabit Ethernet adapters.", bold_prefix="Network Adapters:")
    add_bullet(" Interface queries executed via Get-NetAdapter, MSFT_NetIPInterface, and Win32_NetworkAdapterConfiguration.", bold_prefix="Query Subsystems:")

    add_h2("3.3 Software Interfaces")
    add_bullet(" PostgreSQL 16 via asyncpg connection pool and SQLAlchemy 2.0 ORM.", bold_prefix="Database Engine:")
    add_bullet(" SQLite 3 for endpoint local offline outbox and remediation attempt records.", bold_prefix="Local Storage:")
    add_bullet(" Ollama REST API (http://127.0.0.1:11434) using /api/chat and /api/tags.", bold_prefix="Local AI Provider:")
    add_bullet(" netsh.exe for IPv4 interface address and DNS server assignment; ipconfig.exe for lease release, renewal, and DNS registration; Win32 ctypes.windll.dnsapi.DnsFlushResolverCache() for instantaneous cache clearing.", bold_prefix="Windows OS Subsystems:")

    add_h2("3.4 Communications Interfaces")
    add_bullet(" HTTPS / HTTP REST API with JSON payloads.", bold_prefix="API Protocol:")
    add_bullet(" OAuth2 Password Bearer flow returning cryptographically signed JWT tokens (HMAC-SHA256).", bold_prefix="Authentication:")
    add_bullet(" Periodic HTTP POST heartbeats and batch event synchronization (/api/agents/sync) with exponential backoff.", bold_prefix="Agent Sync:")

    # ==================== 4. SYSTEM FEATURES ====================
    add_h1("4. System Features & Functional Requirements")
    add_h2("4.1 System Feature: Automated Network Failure Detection (10 Conditions)")
    add_h3("4.1.1 Description and Priority")
    add_p("[P1 - Mandatory] The system must automatically collect telemetry and diagnose the 10 general Windows network failure conditions using deterministic rules and local Llama 8B AI reasoning.")

    add_h3("4.1.2 Stimulus/Response Sequences")
    add_p("1. Trigger: User clicks 'Run Diagnosis' in UI, or endpoint agent executes its scheduled periodic health scan.")
    add_p("2. Ingestion: System collects structured telemetry (network_adapter, adapters_list, ip_config, gateway_ping, internet_ping, dns_test, firewall, services).")
    add_p("3. Analysis: Deterministic rule engine evaluates signatures hierarchically. If AI is enabled and Ollama is reachable, telemetry and retrieved KB SOPs are sent to llama3.1:8b.")
    add_p("4. Output: System generates a DiagnosisResult containing root-cause hypotheses, confidence ratings, cited KB documents, and recommended allowlisted tool IDs.")

    add_h3("4.1.3 Functional Requirements")
    fail_table = [
        ("FR-01", "F01: No Adapter Available", "Detects when adapter status is Disabled or Not Present via Get-NetAdapter.", "enable_adapter"),
        ("FR-02", "F02: Media Disconnected", "Detects unplugged LAN cable or disconnected Wi-Fi (MediaConnectionState: 2).", "Physical inspection (KB-NET-006)"),
        ("FR-03", "F03: No Valid IP / APIPA", "Detects APIPA 169.254.x.x addresses or missing IPv4 lease.", "renew_dhcp"),
        ("FR-04", "F04: Gateway Unreachable", "Detects valid IP assigned but default gateway ping experiences 100% loss.", "renew_dhcp / gateway check"),
        ("FR-05", "F05: DNS Resolution Failure", "Detects public IP reachable (8.8.8.8) but domain name resolution fails or static DNS is misconfigured.", "flush_dns_cache & DNS DHCP reset"),
        ("FR-06", "F06: Internet WAN Outage", "Detects gateway responds (0% loss) but external internet (8.8.8.8) has 100% loss.", "ISP/WAN outage flag (KB-NET-007)"),
        ("FR-07", "F07: Firewall Blocked", "Detects Windows Defender Firewall active profile blocking communication.", "Firewall verification (KB-NET-008)"),
        ("FR-08", "F08: Multiple Adapters Conflict", "Detects multiple active physical adapters competing for primary route.", "Adapter prioritization (KB-NET-009)"),
        ("FR-09", "F09: High Latency / Packet Loss", "Detects degraded connection (Latency > 5000ms or Packet Loss >= 20%).", "QoS / AP re-association (KB-NET-010)"),
        ("FR-10", "F10: Critical Service Stopped", "Detects Print Spooler (Spooler), Dhcp, or Dnscache services stopped.", "restart_approved_service")
    ]
    create_styled_table(["Req ID", "Condition", "Detection Logic", "Recommended Action"], fail_table, [0.8, 1.8, 2.4, 1.5])

    add_h2("4.2 System Feature: Real Static IP & Manual DNS to DHCP Remediation")
    add_h3("4.2.1 Description and Priority")
    add_p("[P1 - Mandatory] When a Windows endpoint is manually configured with a static IP or static DNS servers, standard commands like ipconfig /renew fail to acquire a lease. The remediation engine must dynamically resolve the active interface, switch IP and DNS configuration back to DHCP automatic mode via netsh, execute lease renewal, handle elevation requirements, and verify that DHCP is genuinely active.")

    add_h3("4.2.2 Stimulus/Response Sequences")
    add_p("1. Trigger: User clicks 'Execute Remediation & Verify Postcondition' for renew_dhcp or flush_dns_cache.")
    add_p("2. Dynamic Resolution: Executor dynamically inspects Get-NetAdapter and resolves the active physical adapter (e.g., Wi-Fi 2).")
    add_p("3. Execution Sequence:")
    add_bullet(" netsh interface ipv4 set address name='Wi-Fi 2' source=dhcp; netsh interface ipv4 set dnsservers name='Wi-Fi 2' source=dhcp; ipconfig /renew 'Wi-Fi 2'.", bold_prefix="For renew_dhcp:")
    add_bullet(" Checks if DNS is static via netsh interface ipv4 show dnsservers. If static, resets to DHCP via netsh; flushes cache via DnsFlushResolverCache() and Clear-DnsClientCache; re-registers DNS.", bold_prefix="For flush_dns_cache:")
    add_p("4. Elevation Fallback: If non-elevated execution fails with 'requires elevation', system triggers elevated execution (Start-Process -Verb RunAs or sudo.exe).")
    add_p("5. Verification Check: Queries (Get-NetIPInterface).Dhcp and netsh show dnsservers to confirm DHCP is Enabled and DNS is automatic. Pings gateway and tests domain resolution.")
    add_p("6. State Update: If verified, sets incident status to RESOLVED with '[FIXED]'. If elevation fails or verification fails, sets status to ESCALATED with '[FLAGGED: CANNOT BE DONE AUTOMATICALLY]'.")

    add_h3("4.2.3 Functional Requirements")
    add_bullet(" The system shall not hardcode adapter names like 'Wi-Fi'. It shall dynamically resolve the active physical connected interface (e.g., 'Wi-Fi 2').", bold_prefix="FR-11 (Dynamic Adapter Resolution):")
    add_bullet(" The system shall execute netsh interface ipv4 set address ... source=dhcp and netsh interface ipv4 set dnsservers ... source=dhcp followed by ipconfig /renew.", bold_prefix="FR-12 (DHCP Reset Sequence):")
    add_bullet(" The system shall attempt Windows privilege elevation via Start-Process powershell ... -Verb RunAs -Wait or sudo.exe if non-elevated commands return access denied.", bold_prefix="FR-13 (Elevation Management):")
    add_bullet(" Postcondition verification shall verify that (Get-NetIPInterface).Dhcp is 'Enabled', DNS is not 'Statically Configured', IP is valid non-APIPA, and default gateway responds.", bold_prefix="FR-14 (Real Postcondition Verification):")
    add_bullet(" Incidents must be explicitly marked '[FIXED]' upon successful verification or '[FLAGGED: CANNOT BE DONE AUTOMATICALLY]' if execution/verification fails.", bold_prefix="FR-15 (Outcome Flagging):")

    add_h2("4.3 Use Cases / User Stories")
    add_h3("Use Case UC-01: End-to-End Remediation of Misconfigured Manual DNS")
    add_bullet(" Technician / End-User.", bold_prefix="Primary Actor:")
    add_bullet(" User manually configured DNS servers to 8.8.8.8 and 8.8.8.4 on adapter Wi-Fi 2, causing internal domain resolution failure.", bold_prefix="Precondition:")
    add_bullet(" 1. User opens incident in web console and clicks 'Run Diagnosis'. 2. Rule engine detects DNS failure (RULE-NET-003) and retrieves KB-NET-003. 3. System proposes flush_dns_cache. 4. User clicks 'Execute Remediation & Verify Postcondition'. 5. Executor detects Wi-Fi 2, resets DNS servers to DHCP via netsh, flushes cache via DnsFlushResolverCache(), and re-registers DNS. 6. Verifier confirms DNS is automatic and resolves test domains. 7. Status updates to RESOLVED with green '[FIXED]' banner.", bold_prefix="Main Success Scenario:")
    add_bullet(" If Windows denies elevation, executor captures exit code 1. Verifier marks NOT_RESOLVED. Status updates to ESCALATED with red '[FLAGGED: CANNOT BE DONE AUTOMATICALLY]' banner explaining elevation is required.", bold_prefix="Alternative Flow (Elevation Denied):")

    add_h3("Use Case UC-02: Offline Edge Diagnosis During Gateway Loss")
    add_bullet(" Autonomous Windows Endpoint Agent Daemon.", bold_prefix="Primary Actor:")
    add_bullet(" Central server is unreachable due to local gateway failure.", bold_prefix="Precondition:")
    add_bullet(" 1. Agent detects heartbeat failure and enters offline mode. 2. Collects local diagnostics and runs local deterministic rules. 3. RULE-NET-002 matches (APIPA / Gateway Loss). 4. Checks local policy and retry limits. 5. Executes renew_dhcp on active physical adapter. 6. Re-evaluates diagnostics: valid IP obtained (10.12.4.152) and gateway is reachable. 7. Enqueues OFFLINE_REMEDIATION_SUCCESS event in SQLite outbox. 8. When connection is restored, agent synchronizes queued events with central server.", bold_prefix="Main Success Scenario:")

    # ==================== 5. NON-FUNCTIONAL REQUIREMENTS ====================
    add_h1("5. Non-Functional Requirements (NFRs)")
    add_h2("5.1 Performance Requirements")
    add_bullet(" Deterministic rule evaluation shall complete in <= 50 milliseconds.", bold_prefix="NFR-PERF-01 (Diagnostic Latency):")
    add_bullet(" Local Llama 8B parameter inference via Ollama shall generate structured diagnostic output in <= 15 seconds.", bold_prefix="NFR-PERF-02 (AI Inference Latency):")
    add_bullet(" Native Win32 DNS client cache flushing via DnsFlushResolverCache() shall complete in <= 10 milliseconds.", bold_prefix="NFR-PERF-03 (DNS Flush Speed):")
    add_bullet(" REST API endpoints shall respond within <= 200 milliseconds under a concurrency of 100 simultaneous requests.", bold_prefix="NFR-PERF-04 (API Response Bounds):")

    add_h2("5.2 Safety Requirements")
    add_bullet(" All R2 (disruptive) and R3 (high-risk) remediation plans must remain in PENDING state until explicitly approved by an authenticated technician or administrator.", bold_prefix="NFR-SAFE-01 (HITL Approval Gate):")
    add_bullet(" Endpoint agents shall enforce a ceiling of at most 2 automated remediation attempts per root cause within a 300-second cooldown window to prevent flapping.", bold_prefix="NFR-SAFE-02 (Remediation Retry Cap):")
    add_bullet(" In operational mode (mock_mode = False), the system shall never fabricate diagnostic or verification outputs. All returned status codes must reflect actual operating system state.", bold_prefix="NFR-SAFE-03 (Zero Mock Leakage):")

    add_h2("5.3 Security Requirements")
    add_bullet(" All API endpoints (excluding /auth/login) require a valid JWT bearer token. Token claims must enforce RBAC roles (student, faculty, technician, admin).", bold_prefix="NFR-SEC-01 (Authentication & RBAC):")
    add_bullet(" The AI diagnostic prompt architecture must strictly delimit telemetry and KB documents as untrusted data blocks. LLM output must be structurally validated against a Pydantic schema before consumption.", bold_prefix="NFR-SEC-02 (Prompt Injection Defense):")
    add_bullet(" All status transitions, diagnostic runs, approvals, and script execution outputs must be persisted to the audit_events table with immutable timestamps.", bold_prefix="NFR-SEC-03 (Immutable Audit Logging):")
    add_bullet(" Sensitive configuration values (JWT secret keys, database credentials) must be injected strictly via environment variables (.env) and never committed to source control.", bold_prefix="NFR-SEC-04 (Credential Hygiene):")

    add_h2("5.4 Software Quality Attributes")
    add_bullet(" The endpoint agent must maintain full diagnostic functionality and event buffering in the SQLite outbox during complete central server outages.", bold_prefix="NFR-QA-01 (Reliability & Fault Tolerance):")
    add_bullet(" Diagnostic rules and remediation tools must implement base abstract classes (DiagnosticRule, ToolDefinition), enabling new failure condition modules to be registered without modifying core engine logic.", bold_prefix="NFR-QA-02 (Maintainability & Modularity):")
    add_bullet(" The central server shall run seamlessly on Windows and Linux hosts, while the endpoint agent is optimized for Windows 10/11 environments.", bold_prefix="NFR-QA-03 (Portability):")

    add_h2("5.5 Business Rules & Compliance")
    add_bullet(" An incident cannot transition to RESOLVED unless its associated remediation execution record possesses a corresponding VerificationResult with status VERIFIED_RESOLVED.", bold_prefix="BR-01 (Verification Invariant):")
    add_bullet(" Tickets with priority CRITICAL or status ESCALATED must be routed to Tier 2 technicians within 15 minutes of triage.", bold_prefix="BR-02 (Technician Assignment):")

    # ==================== 6. APPENDIX ====================
    add_h1("6. Appendix")
    add_h2("Appendix A: Glossary & Terminology Dictionary")
    add_bullet(" Automatic Private IP Addressing (169.254.0.1 to 169.254.255.254) generated by Windows when DHCP is unreachable.", bold_prefix="APIPA:")
    add_bullet(" An expert system evaluating hard telemetry conditions (loss %, IP strings, service states) using boolean logic without probabilistic variation.", bold_prefix="Deterministic Rule Engine:")
    add_bullet(" A mandatory governance design pattern requiring human technician authorization before executing disruptive system actions.", bold_prefix="HITL (Human-in-the-Loop):")
    add_bullet(" Meta's 8-billion parameter instruction-tuned open weights model executed locally via Ollama.", bold_prefix="Llama 3.1 8B:")
    add_bullet(" Ingestion of IT standard operating procedures into text chunks, enabling semantic search to ground LLM reasoning in verified campus documentation.", bold_prefix="RAG (Retrieval-Augmented Generation):")

    add_h2("Appendix B: Analysis Models (Architecture & Entities)")
    add_p("The AISD architecture employs an event-driven, decoupled design. Client endpoints operate autonomous agents that communicate over asynchronous REST APIs with the central FastAPI server.")
    add_p("The database schema includes normalized tables: users, incidents, incident_comments, diagnostic_runs, diagnostic_evidence, knowledge_documents, remediation_plans, approvals, remediation_executions, verification_results, and audit_events.")

    add_h2("Appendix C: Requirements Traceability Matrix (RTM)")
    rtm_data = [
        ("FR-01", "Detect Disabled Adapter", "Local Agent / Rule Engine", "endpoint-agent/rules.py", "Get-NetAdapter test"),
        ("FR-02", "Detect Disconnected Media", "Local Agent / Rule Engine", "endpoint-agent/rules.py", "MediaState probe"),
        ("FR-03", "Detect APIPA / DHCP Failure", "Central & Local Rules Engine", "backend/app/rules/engine.py", "ipconfig parse test"),
        ("FR-04", "Detect Gateway Loss", "Central & Local Rules Engine", "backend/app/rules/engine.py", "Gateway ping test"),
        ("FR-05", "Detect DNS Failure & Static DNS", "Central & Local Rules Engine", "backend/app/rules/engine.py", "DNS resolve probe"),
        ("FR-06", "Detect Internet WAN Outage", "Central & Local Rules Engine", "backend/app/rules/engine.py", "WAN ping probe"),
        ("FR-07", "Detect Firewall Blocked Traffic", "Central & Local Rules Engine", "backend/app/rules/engine.py", "Firewall profile test"),
        ("FR-08", "Detect Multiple Adapters Conflict", "Central & Local Rules Engine", "backend/app/rules/engine.py", "NetAdapter metric scan"),
        ("FR-09", "Detect Latency / Packet Loss", "Central & Local Rules Engine", "backend/app/rules/engine.py", "ICMP latency test"),
        ("FR-10", "Detect Stopped Windows Services", "Central & Local Rules Engine", "backend/app/rules/engine.py", "Get-Service test"),
        ("FR-11", "Dynamic Adapter Resolution", "Remediation Executor", "backend/app/remediation/executor.py", "Wi-Fi 2 detection test"),
        ("FR-12", "Reset Static IP & DNS to DHCP", "Remediation Executor", "backend/app/remediation/executor.py", "netsh command test"),
        ("FR-13", "Privilege Elevation Handling", "Remediation Executor", "backend/app/remediation/executor.py", "RunAs / sudo invocation"),
        ("FR-14", "Real Postcondition Verification", "Verification Engine", "backend/app/remediation/verifier.py", "CIM / NetIPInterface check"),
        ("FR-15", "Strict FIXED / FLAGGED Status", "Remediation API", "backend/app/api/remediation.py", "Incident status assertion"),
        ("NFR-PERF-02", "Local Llama 8B Reasoning", "Ollama Provider", "backend/app/services/ollama_provider.py", "Ollama chat benchmark"),
        ("NFR-SAFE-01", "HITL Approval Gate", "Policy Engine", "backend/app/remediation/policy.py", "Role permission test"),
        ("NFR-QA-01", "Offline SQLite Outbox Queueing", "Endpoint Storage & Sync", "endpoint-agent/storage.py", "Network disconnect test")
    ]
    create_styled_table(["Req ID", "Requirement Summary", "Component", "Source File", "Verification Method"], rtm_data, [0.8, 1.8, 1.4, 1.5, 1.0])

    # Save
    doc.save(output_path)
    print(f"SRS Document successfully created at: {output_path}")

if __name__ == "__main__":
    out_file = r"e:\AISD\aisd\AISD_Software_Requirements_Specification.docx"
    build_srs_doc(out_file)
