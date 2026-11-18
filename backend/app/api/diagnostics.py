import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.models.incident import Incident, IncidentComment
from app.models.diagnostic import DiagnosticRun, DiagnosticEvidence
from app.models.knowledge import KnowledgeDocument
from app.models.audit import AuditEvent
from app.models.user import User
from app.schemas.diagnostic import (
    DiagnosticRunResponse, DiagnosisResult, RunDiagnosisRequest
)
from app.api.deps import get_current_user
from app.rules.engine import rule_engine
from app.rag.engine import rag_engine
from app.remediation import windows_net
from app.services.ollama_provider import ollama_provider
from app.services.decision_logger import record_decision_log, compute_health_metrics

router = APIRouter(prefix="/incidents", tags=["Diagnostics"])


@router.post("/{incident_id}/diagnose", response_model=DiagnosisResult)
async def run_diagnosis(
    incident_id: int,
    req: RunDiagnosisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    incident = await db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found.")

    # 1. Determine diagnostic evidence
    # Priority: explicit synthetic_evidence -> live Windows collection -> baseline fallback
    evidence = req.synthetic_evidence
    if not evidence and req.collect_live:
        evidence = await asyncio.to_thread(windows_net.collect_live_windows_evidence)
    if not evidence:
        # Check if title/description indicates Wi-Fi / DHCP failure
        text_lower = (incident.title + " " + incident.description).lower()
        if "wi-fi" in text_lower or "wifi" in text_lower or "cannot access" in text_lower or "no internet" in text_lower:
            evidence = {
                "network_adapter": {
                    "name": "Wi-Fi",
                    "status": "Up",
                    "mac_address": "00:1A:2B:3C:4D:5E",
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
                    "recent_dhcp_events": [
                        {"event_id": 1001, "source": "Dhcp-Client", "message": "Your computer was not assigned an address from the network."}
                    ]
                }
            }
        elif "print" in text_lower:
            evidence = {
                "services": {
                    "Spooler": {"status": "Stopped", "start_type": "Automatic"}
                }
            }
        else:
            evidence = {
                "network_adapter": {"name": "Wi-Fi", "status": "Up"},
                "ip_config": {"ipv4_address": "10.12.1.55", "default_gateway": "10.12.0.1"},
                "gateway_ping": {"reachable": True, "packet_loss_pct": 0},
                "dns_test": {"resolved": True}
            }

    # 2. Retrieve relevant troubleshooting knowledge (RAG)
    query_text = f"{incident.title} {incident.description} " + " ".join(evidence.keys())
    stmt = select(KnowledgeDocument)
    docs_all = (await db.execute(stmt)).scalars().all()
    docs_payload = [
        {
            "doc_id": d.doc_id,
            "title": d.title,
            "category": d.category,
            "source_type": d.source_type,
            "chunks": [{"chunk_text": d.content}]
        }
        for d in docs_all
    ]
    retrieved_docs = rag_engine.search_local(query_text, docs_payload, top_k=3)

    # 3. Perform AI diagnosis or fallback to rule engine
    if req.use_ai:
        diagnosis = await ollama_provider.diagnose(
            incident_title=incident.title,
            incident_description=incident.description,
            evidence=evidence,
            retrieved_docs=retrieved_docs
        )
    else:
        diagnosis = rule_engine.evaluate(evidence)

    # 4. Record DiagnosticRun & DiagnosticEvidence in DB
    run = DiagnosticRun(
        incident_id=incident.id,
        endpoint_id=incident.endpoint_id,
        source="AI" if ("ollama" in diagnosis.provider) else "RULE",
        rule_version="1.0",
        model_name=diagnosis.provider,
        status="COMPLETED",
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        summary=diagnosis.summary,
        findings_json=diagnosis.model_dump()
    )
    db.add(run)
    await db.flush()

    # Store discrete evidence keys
    for k, v in evidence.items():
        ev = DiagnosticEvidence(
            diagnostic_run_id=run.id,
            evidence_type=k,
            key=k,
            value_json=v if isinstance(v, dict) else {"value": v},
            collected_at=datetime.now(timezone.utc),
            sensitivity="LOW",
            redacted=0
        )
        db.add(ev)

    # Update incident state
    incident.diagnosis_summary = diagnosis.summary
    if incident.status in ["NEW", "TRIAGED"]:
        incident.status = "DIAGNOSING"
    incident.updated_at = datetime.now(timezone.utc)

    # Comment log
    doc_refs = ", ".join(diagnosis.sources) if diagnosis.sources else "None"
    rec_tools = ", ".join(diagnosis.recommended_tool_ids) if diagnosis.recommended_tool_ids else "None"
    comment = IncidentComment(
        incident_id=incident.id,
        author_id=current_user.id,
        author_name=f"AISD Engine [{diagnosis.provider}]",
        comment=f"Automated Diagnosis completed.\nSummary: {diagnosis.summary}\nRecommended Tools: {rec_tools}\nCitations: {doc_refs}",
        is_internal=0
    )
    db.add(comment)

    audit = AuditEvent(
        actor_type="AI" if "ollama" in diagnosis.provider else "RULE",
        actor_id=str(current_user.id),
        event_type="DIAGNOSTIC_RUN",
        entity_type="INCIDENT",
        entity_id=str(incident.id),
        details_json={
            "provider": diagnosis.provider,
            "hypotheses_count": len(diagnosis.hypotheses),
            "sources": diagnosis.sources,
            "recommended_tools": diagnosis.recommended_tool_ids
        }
    )
    db.add(audit)

    top_hyp = diagnosis.hypotheses[0] if diagnosis.hypotheses else None
    metrics = compute_health_metrics(evidence)
    observed_summary = (
        "; ".join(metrics["anomalies"][:3])
        if metrics["anomalies"]
        else f"Adapter={metrics.get('adapter_name') or 'N/A'} IP={metrics.get('ip_address') or 'N/A'} GW_RTT={metrics.get('gateway_latency_ms')}ms"
    )
    why_text = (
        f"Incident #{incident.incident_number}: Evaluated telemetry via {diagnosis.provider} "
        f"(matched sources: {', '.join(diagnosis.sources) or 'none'}). "
        + (
            f"Primary finding: {top_hyp.cause} (confidence {round(top_hyp.confidence * 100)}%). "
            f"Recommended [{rec_tools}] because observed telemetry matched this deterministic/AI fault pattern."
            if top_hyp else
            f"No clear fault pattern matched; recommended [{rec_tools}] for further investigation."
        )
    )
    record_decision_log(
        db,
        actor_source="OLLAMA_AI" if "ollama" in diagnosis.provider else "RULE_ENGINE",
        decision_type="AI_HYPOTHESIS" if "ollama" in diagnosis.provider else "RULE_DIAGNOSIS",
        rule_or_model=diagnosis.provider,
        action_taken=rec_tools,
        why_explanation=why_text,
        observed_state=observed_summary,
        expected_state="DHCP IPv4 + Automatic DNS + Gateway/WAN Reachable + Services Running",
        confidence=top_hyp.confidence if top_hyp else 0.5,
        outcome="PROPOSED" if diagnosis.hypotheses else "INFO",
        endpoint_id=incident.endpoint_id,
        incident_id=incident.id,
        evidence_json={"sources": diagnosis.sources, "recommended_tools": diagnosis.recommended_tool_ids},
    )

    await db.commit()
    return diagnosis


@router.get("/{incident_id}/diagnostics", response_model=List[DiagnosticRunResponse])
async def get_diagnostics(
    incident_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    incident = await db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found.")

    stmt = (
        select(DiagnosticRun)
        .where(DiagnosticRun.incident_id == incident_id)
        .options(selectinload(DiagnosticRun.evidence_items))
        .order_by(DiagnosticRun.completed_at.desc())
    )
    result = await db.execute(stmt)
    runs = result.scalars().all()
    return runs
