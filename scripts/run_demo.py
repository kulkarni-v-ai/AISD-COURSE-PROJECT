#!/usr/bin/env python3
"""
AISD - AI-POWERED IT INCIDENT MANAGEMENT SYSTEM
Demonstration Script for Scenario 1:
"My laptop is connected to the college Wi-Fi, but I cannot access anything."
"""

import sys
import os
import json
import asyncio
from datetime import datetime

# Add backend to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from app.db.session import init_db, AsyncSessionLocal
from app.main import seed_initial_data
from app.models.incident import Incident
from app.models.diagnostic import DiagnosticRun, DiagnosticEvidence
from app.models.remediation import RemediationPlan, Approval, RemediationExecution, VerificationResult
from app.models.knowledge import KnowledgeDocument
from app.models.audit import AuditEvent
from app.models.user import User

from app.rules.engine import rule_engine
from app.rag.engine import rag_engine
from app.services.ollama_provider import ollama_provider
from app.remediation.policy import policy_engine
from app.remediation.executor import remediation_executor


def banner(title):
    print("\n" + "=" * 70)
    print(f" {title.upper()}")
    print("=" * 70)


async def run_scenario():
    banner("AISD Automated Incident Diagnosis & Remediation Demonstration")
    await init_db()
    await seed_initial_data()

    async with AsyncSessionLocal() as session:
        # Step 1: Create Incident
        banner("Step 1: Student Incident Reported")
        title = "My laptop is connected to the college Wi-Fi, but I cannot access anything."
        description = "Connected to Campus-Student-WiFi in the Main Library. Network icon shows 'No Internet, secured'. Cannot browse college intranet or any web page."
        
        inc = Incident(
            incident_number=f"INC-DEMO-{int(datetime.now().timestamp())}",
            reporter_id=3, # Student user
            title=title,
            description=description,
            category="NETWORK",
            priority="HIGH",
            status="NEW"
        )
        session.add(inc)
        await session.commit()
        await session.refresh(inc)
        print(f"Ticket Created:   {inc.incident_number}")
        print(f"Reporter:         Student (Ananya Sharma)")
        print(f"Issue Title:      {inc.title}")
        print(f"Current Status:   {inc.status}")

        # Step 2: Evidence Collection
        banner("Step 2: Collecting Endpoint Diagnostic Evidence")
        collected_evidence = {
            "network_adapter": {
                "name": "Wi-Fi",
                "status": "Up",
                "mac": "00:1A:2B:3C:4D:5E",
                "ssid": "Campus-Student-WiFi"
            },
            "ip_config": {
                "ipv4_address": "169.254.88.192",
                "subnet_mask": "255.255.0.0",
                "default_gateway": None,
                "dhcp_enabled": True
            },
            "gateway_ping": {
                "reachable": False,
                "packet_loss_pct": 100,
                "target_gateway": None
            },
            "dns_test": {
                "resolved": False,
                "target_domain": "intranet.college.edu",
                "error": "DNS_PROBE_FINISHED_NO_INTERNET"
            },
            "event_log": {
                "recent_events": [
                    {"event_id": 1001, "source": "Dhcp-Client", "message": "Your computer was not assigned an address from the network."}
                ]
            }
        }
        print("Observed Facts:")
        print(f"  - Wi-Fi Adapter:      Up (Connected to 'Campus-Student-WiFi')")
        print(f"  - IPv4 Address:       {collected_evidence['ip_config']['ipv4_address']} (APIPA link-local auto-configuration)")
        print(f"  - Default Gateway:    None")
        print(f"  - Gateway Ping:       100% packet loss (unreachable)")
        print(f"  - DNS Resolution:     Failed (intranet.college.edu)")

        # Step 3 & 4: Diagnostic Rule Matching & Ollama AI Diagnosis
        banner("Step 3 & 4: Diagnostic Reasoning & Ollama Analysis")
        
        # RAG Knowledge Retrieval
        print("Searching Approved Knowledge Base (RAG)...")
        rag_query = f"{title} {description} 169.254 dhcp lease"
        from sqlalchemy.future import select
        docs_all = (await session.execute(select(KnowledgeDocument))).scalars().all()
        docs_payload = [
            {"doc_id": d.doc_id, "title": d.title, "category": d.category, "chunks": [{"chunk_text": d.content}]}
            for d in docs_all
        ]
        retrieved_docs = rag_engine.search_local(rag_query, docs_payload, top_k=2)
        for r in retrieved_docs:
            print(f"  -> Retrieved [{r['doc_id']}]: {r['title']} (Similarity: {r['similarity_score']})")

        # Run AI diagnosis (with fallback to deterministic rules)
        diagnosis = await ollama_provider.diagnose(
            incident_title=title,
            incident_description=description,
            evidence=collected_evidence,
            retrieved_docs=retrieved_docs
        )

        print(f"\nDiagnosis Provider: {diagnosis.provider}")
        print(f"Diagnosis Summary:  {diagnosis.summary}")
        print("Hypotheses:")
        for h in diagnosis.hypotheses:
            print(f"  * Root Cause: {h.cause} ({int(h.confidence * 100)}% confidence)")
            print(f"    Evidence Keys: {h.evidence_ids}")
            print(f"    Next Checks:   {h.next_checks}")
        print(f"Retrieved SOP Citations: {diagnosis.sources}")
        print(f"Recommended Tool IDs:    {diagnosis.recommended_tool_ids}")

        # Update Incident status
        inc.status = "DIAGNOSING"
        inc.diagnosis_summary = diagnosis.summary
        await session.commit()

        # Step 5 & 6: Propose Remediation & Policy Check
        banner("Step 5 & 6: Remediation Planning & Policy Check")
        chosen_tool = diagnosis.recommended_tool_ids[0] if diagnosis.recommended_tool_ids else "renew_dhcp"
        
        # Policy Evaluation
        allowed, reason, tool_def, approval_required = policy_engine.evaluate_plan_creation(
            tool_id=chosen_tool,
            arguments={"adapter_name": "Wi-Fi"},
            user_role="technician"
        )
        print(f"Proposed Tool:        {tool_def.name} ({chosen_tool})")
        print(f"Risk Classification:  {tool_def.risk_level} (Disruptive / Reversible)")
        print(f"Policy Compliant:     {allowed} ({reason})")
        print(f"Approval Required:    {approval_required} (Technician authorization mandatory)")

        plan = RemediationPlan(
            incident_id=inc.id,
            tool_id=chosen_tool,
            arguments_json={"adapter_name": "Wi-Fi"},
            reason="Automated action plan to re-acquire DHCP lease and restore campus connectivity.",
            risk_level=tool_def.risk_level,
            approval_required=1 if approval_required else 0,
            status="PENDING"
        )
        session.add(plan)
        inc.status = "APPROVAL_REQUIRED"
        await session.commit()
        await session.refresh(plan)

        # Step 7: Technician Approval
        banner("Step 7: Applying Approval Workflow")
        print("Technician 'Rajesh Kumar' inspects plan and evidence...")
        approval = Approval(
            remediation_plan_id=plan.id,
            approver_user_id=2, # Tech
            decision="APPROVED",
            reason="Verified client has valid credentials and AP DHCP scope is active."
        )
        session.add(approval)
        plan.status = "APPROVED"
        inc.status = "ACTION_PLANNED"
        await session.commit()
        print(f"Remediation Plan #{plan.id} APPROVED by Technician.")

        # Step 8 & 9: Controlled Execution
        banner("Step 8 & 9: Controlled Endpoint Remediation Execution")
        print(f"Executing tool '{chosen_tool}' in controlled MOCK mode...")
        exec_status, exit_code, out_str, err_str, v_status, v_evidence = await remediation_executor.execute(
            tool_id=chosen_tool,
            arguments=plan.arguments_json,
            is_mock=True,
            simulate_outcome="VERIFIED_RESOLVED"
        )
        print(f"Execution Status: {exec_status} (Exit Code: {exit_code})")
        print("Execution Log:")
        for line in out_str.strip().split("\n"):
            print(f"  {line}")

        execution = RemediationExecution(
            remediation_plan_id=plan.id,
            tool_id=chosen_tool,
            execution_status=exec_status,
            exit_code=exit_code,
            output_redacted=out_str,
            is_mock=1
        )
        session.add(execution)
        await session.flush()

        # Step 10 & 11: Postcondition Verification
        banner("Step 10 & 11: Postcondition Verification")
        verification = VerificationResult(
            execution_id=execution.id,
            verification_type=tool_def.verification_type,
            status=v_status,
            evidence_json=v_evidence
        )
        session.add(verification)
        
        print(f"Postcondition Verification Status: {v_status}")
        print("Post-Action Telemetry:")
        print(f"  - New IPv4 Address:    {v_evidence.get('ip_address')}")
        print(f"  - Subnet Mask:         {v_evidence.get('subnet_mask')}")
        print(f"  - Default Gateway:     {v_evidence.get('default_gateway')}")
        print(f"  - Gateway Ping Latency:{v_evidence.get('gateway_ping_latency_ms')} ms")

        # Step 12: Resolution
        banner("Step 12: Final Resolution State")
        if v_status == "VERIFIED_RESOLVED":
            inc.status = "RESOLVED"
            inc.resolved_at = datetime.now()
            inc.resolution_summary = f"Issue verified resolved via tool '{chosen_tool}'. Post-action verification confirmed valid IP configuration ({v_evidence.get('ip_address')}) and active gateway reachability."
            print(f"Ticket Status: RESOLVED [SUCCESS]")
            print(f"Resolution Summary: {inc.resolution_summary}")
        else:
            inc.status = "ESCALATED"
            print("Ticket Status: ESCALATED [Action completed but verification failed]")

        await session.commit()
        banner("End-To-End Scenario Completed Successfully")


if __name__ == "__main__":
    asyncio.run(run_scenario())
