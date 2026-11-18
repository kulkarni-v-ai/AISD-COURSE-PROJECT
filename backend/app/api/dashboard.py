import asyncio
from datetime import datetime, timezone
from typing import Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, desc

from app.core.config import settings
from app.db.session import get_db
from app.models.incident import Incident
from app.models.endpoint import Endpoint
from app.models.audit import AuditEvent
from app.models.monitoring import EndpointTelemetrySnapshot, AgentTask, AgentDecisionLog
from app.models.remediation import RemediationExecution, VerificationResult
from app.models.user import User
from app.api.deps import get_current_user
from app.api.agents import detect_server_lan_ips, _serialize_task
from app.remediation import windows_net
from app.rules.engine import rule_engine
from app.services.decision_logger import record_telemetry_snapshot, record_decision_log, compute_health_metrics

router = APIRouter(prefix="/dashboard", tags=["Dashboard & Metrics"])


class CollectProbeRequest(BaseModel):
    agent_uuid: Optional[str] = None
    mode: str = "auto"  # auto | direct_server | remote_agent


async def _check_ollama_status() -> dict:
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            res = await client.get(f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/tags")
            if res.status_code == 200:
                models = [m.get("name", "") for m in res.json().get("models", [])]
                return {"reachable": True, "model": settings.OLLAMA_MODEL, "loaded_models": models}
    except Exception:
        pass
    return {"reachable": False, "model": settings.OLLAMA_MODEL, "loaded_models": []}


@router.get("/stats")
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    total_incidents = (await db.execute(select(func.count(Incident.id)))).scalar() or 0
    resolved_incidents = (await db.execute(select(func.count(Incident.id)).where(Incident.status == "RESOLVED"))).scalar() or 0
    escalated_incidents = (await db.execute(select(func.count(Incident.id)).where(Incident.status == "ESCALATED"))).scalar() or 0
    in_progress = (await db.execute(select(func.count(Incident.id)).where(Incident.status.in_(["DIAGNOSING", "ACTION_PLANNED", "APPROVAL_REQUIRED", "REMEDIATING", "VERIFYING"])))).scalar() or 0
    new_incidents = (await db.execute(select(func.count(Incident.id)).where(Incident.status.in_(["NEW", "TRIAGED"])))).scalar() or 0

    online_endpoints = (await db.execute(select(func.count(Endpoint.id)).where(Endpoint.status == "ONLINE"))).scalar() or 0
    total_endpoints = (await db.execute(select(func.count(Endpoint.id)))).scalar() or 0

    total_executions = (await db.execute(select(func.count(RemediationExecution.id)))).scalar() or 0
    verified_resolutions = (await db.execute(select(func.count(VerificationResult.id)).where(VerificationResult.status == "VERIFIED_RESOLVED"))).scalar() or 0
    success_rate = round((verified_resolutions / total_executions * 100), 1) if total_executions > 0 else 100.0

    cat_stmt = select(Incident.category, func.count(Incident.id)).group_by(Incident.category)
    cat_rows = (await db.execute(cat_stmt)).all()
    by_category = {cat: count for cat, count in cat_rows}

    pri_stmt = select(Incident.priority, func.count(Incident.id)).group_by(Incident.priority)
    pri_rows = (await db.execute(pri_stmt)).all()
    by_priority = {pri: count for pri, count in pri_rows}

    audit_stmt = select(AuditEvent).order_by(desc(AuditEvent.created_at)).limit(10)
    audit_events = (await db.execute(audit_stmt)).scalars().all()

    return {
        "overview": {
            "total_incidents": total_incidents,
            "new_incidents": new_incidents,
            "in_progress": in_progress,
            "resolved_incidents": resolved_incidents,
            "escalated_incidents": escalated_incidents,
            "active_endpoints": online_endpoints,
            "total_endpoints": total_endpoints,
            "verified_remediation_rate_pct": success_rate,
        },
        "by_category": by_category,
        "by_priority": by_priority,
        "recent_audits": [
            {
                "id": a.id,
                "actor_type": a.actor_type,
                "actor_id": a.actor_id,
                "event_type": a.event_type,
                "entity_type": a.entity_type,
                "entity_id": a.entity_id,
                "created_at": a.created_at,
                "details": a.details_json,
            }
            for a in audit_events
        ],
    }


@router.get("/monitor")
async def get_monitoring_dashboard(
    agent_uuid: Optional[str] = None,
    limit: int = 40,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stats = await get_dashboard_stats(db=db, current_user=current_user)
    ollama_info = await _check_ollama_status()
    lan_ips = detect_server_lan_ips()
    primary_ip = lan_ips[0] if lan_ips else "127.0.0.1"

    ep_stmt = select(Endpoint).order_by(Endpoint.last_seen_at.desc())
    endpoints = (await db.execute(ep_stmt)).scalars().all()

    selected_ep = None
    if agent_uuid:
        selected_ep = next((e for e in endpoints if e.agent_uuid == agent_uuid), None)
    if not selected_ep and endpoints:
        # Prefer endpoint with live telemetry or most recently seen online host
        with_telemetry = [e for e in endpoints if e.last_telemetry_json]
        selected_ep = with_telemetry[0] if with_telemetry else endpoints[0]

    selected_uuid = selected_ep.agent_uuid if selected_ep else None

    # Fetch chronological snapshots for selected endpoint (or latest fleet snapshots)
    snap_query = select(EndpointTelemetrySnapshot).order_by(desc(EndpointTelemetrySnapshot.recorded_at)).limit(min(limit, 80))
    if selected_uuid:
        snap_query = snap_query.where(EndpointTelemetrySnapshot.agent_uuid == selected_uuid)
    snaps_desc = (await db.execute(snap_query)).scalars().all()
    snaps = list(reversed(snaps_desc))

    time_series = [
        {
            "id": s.id,
            "recorded_at": s.recorded_at,
            "hostname": s.hostname,
            "ip_address": s.ip_address,
            "adapter_name": s.adapter_name,
            "adapter_status": s.adapter_status,
            "dhcp_enabled": (None if s.dhcp_enabled is None else bool(s.dhcp_enabled)),
            "dns_dhcp_enabled": (None if s.dns_dhcp_enabled is None else bool(s.dns_dhcp_enabled)),
            "gateway_latency_ms": s.gateway_latency_ms,
            "internet_latency_ms": s.internet_latency_ms,
            "gateway_loss_pct": s.gateway_loss_pct,
            "internet_loss_pct": s.internet_loss_pct,
            "dns_resolved": (None if s.dns_resolved is None else bool(s.dns_resolved)),
            "services_running_count": s.services_running_count,
            "services_total_count": s.services_total_count,
            "health_score": s.health_score,
            "anomaly_count": s.anomaly_count,
            "source_mode": s.source_mode,
        }
        for s in snaps
    ]

    latest_snap = snaps[-1] if snaps else None
    latest_telemetry = (
        latest_snap.telemetry_json
        if latest_snap and latest_snap.telemetry_json
        else (selected_ep.last_telemetry_json if selected_ep else None)
    )
    latest_metrics = compute_health_metrics(latest_telemetry) if latest_telemetry else None

    # Decision logs with explicit WHY explanations
    dec_stmt = select(AgentDecisionLog).order_by(desc(AgentDecisionLog.created_at)).limit(60)
    decision_rows = (await db.execute(dec_stmt)).scalars().all()
    decision_logs = [
        {
            "id": d.id,
            "log_uuid": d.log_uuid,
            "agent_uuid": d.agent_uuid,
            "hostname": d.hostname,
            "incident_id": d.incident_id,
            "actor_source": d.actor_source,
            "decision_type": d.decision_type,
            "rule_or_model": d.rule_or_model,
            "action_taken": d.action_taken,
            "why_explanation": d.why_explanation,
            "observed_state": d.observed_state,
            "expected_state": d.expected_state,
            "confidence": d.confidence,
            "outcome": d.outcome,
            "evidence": d.evidence_json or {},
            "created_at": d.created_at,
        }
        for d in decision_rows
    ]

    # Recent remote execution tasks across fleet
    task_stmt = select(AgentTask).order_by(desc(AgentTask.created_at)).limit(25)
    task_rows = (await db.execute(task_stmt)).scalars().all()
    recent_tasks = [_serialize_task(t) for t in task_rows]

    now_ts = datetime.now(timezone.utc).timestamp()
    serialized_endpoints = []
    for ep in endpoints:
        ep_metrics = compute_health_metrics(ep.last_telemetry_json) if ep.last_telemetry_json else None
        last_seen_ts = ep.last_seen_at.timestamp() if ep.last_seen_at else 0
        is_stale = (now_ts - last_seen_ts) > 120 if last_seen_ts else True
        serialized_endpoints.append({
            "id": ep.id,
            "agent_uuid": ep.agent_uuid,
            "hostname": ep.hostname,
            "os_name": ep.os_name,
            "os_version": ep.os_version,
            "agent_version": ep.agent_version,
            "ip_address": ep.ip_address or (ep_metrics.get("ip_address") if ep_metrics else None),
            "adapter_name": ep.adapter_name or (ep_metrics.get("adapter_name") if ep_metrics else None),
            "mac_address": ep.mac_address,
            "status": ep.status,
            "stale": is_stale,
            "last_seen_at": ep.last_seen_at,
            "metrics": ep_metrics,
        })

    return {
        "server_status": {
            "api": "HEALTHY",
            "database": "CONNECTED",
            "ollama_reachable": ollama_info["reachable"],
            "ollama_model": ollama_info["model"],
            "mock_remediation": settings.REMEDIATION_MOCK_MODE,
            "lan_ips": lan_ips,
            "primary_lan_ip": primary_ip,
            "backend_port": settings.PORT,
            "join_command": f"python agent.py --server http://{primary_ip}:{settings.PORT} daemon",
        },
        "selected_agent_uuid": selected_uuid,
        "endpoints": serialized_endpoints,
        "latest_telemetry": latest_telemetry,
        "latest_metrics": latest_metrics,
        "latest_provenance": {
            "source_mode": latest_snap.source_mode if latest_snap else ("ENROLLED" if selected_ep else "NONE"),
            "recorded_at": latest_snap.recorded_at if latest_snap else (selected_ep.last_seen_at if selected_ep else None),
            "hostname": selected_ep.hostname if selected_ep else None,
        },
        "time_series": time_series,
        "decision_logs": decision_logs,
        "recent_tasks": recent_tasks,
        **stats,
    }


@router.post("/collect-probe")
async def collect_live_probe(
    req: CollectProbeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ["technician", "admin"]:
        raise HTTPException(status_code=403, detail="Only technicians and administrators can run live diagnostic probes.")

    import socket as _sock
    local_hostname = _sock.gethostname().lower()

    ep = None
    if req.agent_uuid:
        ep = (await db.execute(select(Endpoint).where(Endpoint.agent_uuid == req.agent_uuid))).scalar_one_or_none()
    else:
        ep = (
            await db.execute(
                select(Endpoint)
                .where(func.lower(Endpoint.hostname) == local_hostname)
                .order_by(Endpoint.last_seen_at.desc())
                .limit(1)
            )
        ).scalars().first()
        if not ep:
            ep = (
                await db.execute(select(Endpoint).order_by(Endpoint.last_seen_at.desc()).limit(1))
            ).scalars().first()

    is_remote_host = bool(ep and ep.hostname and ep.hostname.lower() != local_hostname)

    # Dispatch remote probe when explicitly requested OR when the selected target is another LAN host
    if ep and (req.mode == "remote_agent" or (req.mode == "auto" and is_remote_host)):
        import uuid as _uuid

        task = AgentTask(
            task_uuid=f"task-{_uuid.uuid4().hex[:12]}",
            endpoint_id=ep.id,
            agent_uuid=ep.agent_uuid,
            target_hostname=ep.hostname,
            tool_id="collect_network_status",
            arguments_json={},
            reason=f"Live telemetry probe requested by {current_user.name}",
            requested_by_user_id=current_user.id,
            requested_by_name=current_user.name,
            status="PENDING",
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
        return {"mode": "REMOTE_DISPATCHED", "task": _serialize_task(task)}

    # Collect directly from local Windows host (or fallback to server endpoint)
    evidence = await asyncio.to_thread(windows_net.collect_live_windows_evidence)
    diag = rule_engine.evaluate(evidence)
    metrics = compute_health_metrics(evidence)

    if not ep:
        import platform as _plat

        ep = Endpoint(
            agent_uuid=f"srv-{_sock.gethostname().lower()}",
            hostname=_sock.gethostname(),
            os_name="Windows",
            os_version=f"{_plat.system()} {_plat.release()}",
            agent_version="1.0.0",
            status="ONLINE",
        )
        db.add(ep)
        await db.flush()

    snap, _ = record_telemetry_snapshot(
        db,
        endpoint_id=ep.id,
        agent_uuid=ep.agent_uuid,
        hostname=ep.hostname,
        telemetry=evidence,
        source_mode="SERVER_LOCAL",
        fallback_ip=metrics.get("ip_address"),
    )
    ep.last_telemetry_json = evidence
    if metrics.get("ip_address"):
        ep.ip_address = metrics["ip_address"]
    if metrics.get("adapter_name"):
        ep.adapter_name = metrics["adapter_name"]
    ep.last_seen_at = datetime.now(timezone.utc)
    ep.status = "ONLINE"

    top_hyp = diag.hypotheses[0] if diag.hypotheses else None
    record_decision_log(
        db,
        actor_source="RULE_ENGINE",
        decision_type="RULE_DIAGNOSIS" if top_hyp else "HEALTH_CHECK",
        rule_or_model=", ".join(diag.sources) if diag.sources else "LiveWindowsProbe",
        action_taken=", ".join(diag.recommended_tool_ids) if diag.recommended_tool_ids else "none",
        why_explanation=(
            f"On-demand live probe on '{ep.hostname}': {top_hyp.cause}. Evaluated rules recommended {diag.recommended_tool_ids}."
            if top_hyp
            else f"On-demand live probe on '{ep.hostname}': Health score {metrics['health_score']}/100. Adapter={metrics.get('adapter_name')} ({metrics.get('ip_address')}), GW_RTT={metrics.get('gateway_latency_ms')}ms, WAN_RTT={metrics.get('internet_latency_ms')}ms, DNS={'OK' if metrics.get('dns_resolved') else 'FAIL'}. No remediation needed."
        ),
        observed_state="; ".join(metrics["anomalies"]) if metrics["anomalies"] else f"Healthy ({metrics['health_score']}/100)",
        expected_state="DHCP IP + Automatic DNS + Gateway/WAN Reachable + 4/4 Services Running",
        confidence=top_hyp.confidence if top_hyp else 1.0,
        outcome="PROPOSED" if top_hyp else "RESOLVED",
        endpoint_id=ep.id,
        agent_uuid=ep.agent_uuid,
        hostname=ep.hostname,
        evidence_json=metrics,
    )

    await db.commit()
    return {
        "mode": "DIRECT_COLLECTED",
        "snapshot_id": snap.id,
        "agent_uuid": ep.agent_uuid,
        "metrics": metrics,
        "diagnosis": diag.model_dump(),
    }
