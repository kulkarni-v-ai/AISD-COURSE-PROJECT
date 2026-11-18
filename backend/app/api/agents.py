import socket
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.session import get_db
from app.core.config import settings
from app.models.endpoint import Endpoint
from app.models.sync import EndpointSyncEvent
from app.models.incident import Incident
from app.models.diagnostic import DiagnosticRun
from app.models.monitoring import EndpointTelemetrySnapshot, AgentTask, AgentDecisionLog
from app.models.user import User
from app.schemas.agent import (
    AgentEnrollRequest,
    AgentEnrollResponse,
    AgentHeartbeatRequest,
    AgentSyncBatchRequest,
    AgentSyncBatchResponse,
    AgentTaskCreateRequest,
    AgentBroadcastTaskRequest,
    AgentTaskResultRequest,
)
from app.api.deps import get_current_user
from app.services.decision_logger import compute_health_metrics, record_telemetry_snapshot, record_decision_log

router = APIRouter(prefix="/agents", tags=["Endpoint Agents"])

REMOTE_ALLOWED_TOOLS = {
    "collect_network_status",
    "diagnose_and_auto_remediate",
    "renew_dhcp",
    "flush_dns_cache",
    "enable_adapter",
    "restart_approved_service",
    "test_gateway",
    "test_dns",
}
APPROVED_SERVICES = {"Spooler", "Dhcp", "Dnscache"}


def detect_server_lan_ips() -> List[str]:
    ips: List[str] = []
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        primary_ip = sock.getsockname()[0]
        sock.close()
        if primary_ip and not primary_ip.startswith("127.") and not primary_ip.startswith("169.254."):
            ips.append(primary_ip)
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and not ip.startswith("169.254.") and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    return ips


def _validate_remote_tool(tool_id: str, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    args = dict(arguments or {})
    if tool_id not in REMOTE_ALLOWED_TOOLS:
        raise HTTPException(
            status_code=400,
            detail=f"Tool '{tool_id}' is not allowlisted for remote endpoint execution.",
        )
    if tool_id == "restart_approved_service":
        srv = str(args.get("service_name") or "Spooler")
        if srv not in APPROVED_SERVICES:
            raise HTTPException(
                status_code=400,
                detail=f"Service '{srv}' is not in approved service list ({sorted(APPROVED_SERVICES)}).",
            )
        args["service_name"] = srv
    return args


def _serialize_task(t: AgentTask) -> Dict[str, Any]:
    return {
        "id": t.id,
        "task_uuid": t.task_uuid,
        "endpoint_id": t.endpoint_id,
        "agent_uuid": t.agent_uuid,
        "target_hostname": t.target_hostname,
        "tool_id": t.tool_id,
        "arguments": t.arguments_json or {},
        "reason": t.reason,
        "requested_by_name": t.requested_by_name,
        "status": t.status,
        "result_status": t.result_status,
        "verification_status": t.verification_status,
        "output_text": t.output_text,
        "error_text": t.error_text,
        "result": t.result_json,
        "created_at": t.created_at,
        "dispatched_at": t.dispatched_at,
        "completed_at": t.completed_at,
    }


@router.post("/enroll", response_model=AgentEnrollResponse)
async def enroll_agent(req: AgentEnrollRequest, request: Request, db: AsyncSession = Depends(get_db)):
    stmt = select(Endpoint).where(Endpoint.agent_uuid == req.agent_uuid)
    endpoint = (await db.execute(stmt)).scalar_one_or_none()
    client_ip = req.ip_address or (request.client.host if request.client else None)

    if not endpoint:
        endpoint = Endpoint(
            agent_uuid=req.agent_uuid,
            hostname=req.hostname,
            os_name=req.os_name,
            os_version=req.os_version,
            agent_version=req.agent_version,
            ip_address=client_ip,
            adapter_name=req.adapter_name,
            mac_address=req.mac_address,
            last_telemetry_json=req.telemetry,
            last_seen_at=datetime.now(timezone.utc),
            status="ONLINE",
        )
        db.add(endpoint)
        await db.flush()
        msg = "Endpoint enrolled successfully."
        record_decision_log(
            db,
            actor_source="ONLINE_AGENT",
            decision_type="HEALTH_CHECK",
            rule_or_model="AgentEnrollment",
            action_taken="enroll",
            why_explanation=f"New endpoint '{req.hostname}' ({client_ip or 'LAN'}) enrolled into fleet and established central polling channel.",
            observed_state=f"OS={req.os_name} {req.os_version}, IP={client_ip or 'N/A'}",
            expected_state="Registered active endpoint on LAN",
            confidence=1.0,
            outcome="INFO",
            endpoint_id=endpoint.id,
            agent_uuid=endpoint.agent_uuid,
            hostname=endpoint.hostname,
        )
    else:
        endpoint.hostname = req.hostname
        endpoint.os_version = req.os_version
        endpoint.agent_version = req.agent_version
        if client_ip:
            endpoint.ip_address = client_ip
        if req.adapter_name:
            endpoint.adapter_name = req.adapter_name
        if req.mac_address:
            endpoint.mac_address = req.mac_address
        if req.telemetry is not None:
            endpoint.last_telemetry_json = req.telemetry
        endpoint.last_seen_at = datetime.now(timezone.utc)
        endpoint.status = "ONLINE"
        msg = "Endpoint registration refreshed."

    if req.telemetry:
        _, metrics = record_telemetry_snapshot(
            db,
            endpoint_id=endpoint.id,
            agent_uuid=endpoint.agent_uuid,
            hostname=endpoint.hostname,
            telemetry=req.telemetry,
            source_mode="AGENT_ONLINE",
            fallback_ip=client_ip,
        )
        if not endpoint.ip_address and metrics.get("ip_address"):
            endpoint.ip_address = metrics["ip_address"]
        if not endpoint.adapter_name and metrics.get("adapter_name"):
            endpoint.adapter_name = metrics["adapter_name"]

    await db.commit()
    await db.refresh(endpoint)

    return AgentEnrollResponse(
        endpoint_id=endpoint.id,
        agent_uuid=endpoint.agent_uuid,
        status="ONLINE",
        message=msg,
    )


@router.post("/heartbeat")
async def agent_heartbeat(req: AgentHeartbeatRequest, request: Request, db: AsyncSession = Depends(get_db)):
    stmt = select(Endpoint).where(Endpoint.agent_uuid == req.agent_uuid)
    endpoint = (await db.execute(stmt)).scalar_one_or_none()
    if not endpoint:
        raise HTTPException(status_code=404, detail="Agent not found. Please enroll first.")

    prev_anomalies = (
        compute_health_metrics(endpoint.last_telemetry_json).get("anomalies", [])
        if endpoint.last_telemetry_json
        else []
    )

    client_ip = req.ip_address or (request.client.host if request.client else None)
    if client_ip and not str(client_ip).startswith("127."):
        endpoint.ip_address = client_ip
    elif req.ip_address:
        endpoint.ip_address = req.ip_address
    if req.adapter_name:
        endpoint.adapter_name = req.adapter_name
    if req.mac_address:
        endpoint.mac_address = req.mac_address

    endpoint.last_seen_at = datetime.now(timezone.utc)
    endpoint.status = req.status or "ONLINE"

    if req.telemetry:
        _, metrics = record_telemetry_snapshot(
            db,
            endpoint_id=endpoint.id,
            agent_uuid=endpoint.agent_uuid,
            hostname=endpoint.hostname,
            telemetry=req.telemetry,
            source_mode="AGENT_ONLINE",
            fallback_ip=endpoint.ip_address,
        )
        endpoint.last_telemetry_json = req.telemetry
        if metrics.get("ip_address"):
            endpoint.ip_address = metrics["ip_address"]
        if metrics.get("adapter_name"):
            endpoint.adapter_name = metrics["adapter_name"]

        curr_anomalies = metrics.get("anomalies", [])
        if curr_anomalies != prev_anomalies:
            if curr_anomalies:
                record_decision_log(
                    db,
                    actor_source="ONLINE_AGENT",
                    decision_type="HEALTH_CHECK",
                    rule_or_model="TelemetryWatchdog",
                    action_taken="report_anomaly",
                    why_explanation=(
                        f"Telemetry watchdog on '{endpoint.hostname}' detected state transition to degraded health "
                        f"(score {metrics['health_score']}/100): {'; '.join(curr_anomalies)}."
                    ),
                    observed_state="; ".join(curr_anomalies),
                    expected_state="DHCP IP + Automatic DNS + Gateway/WAN Reachable + 4/4 Core Services Running",
                    confidence=0.95,
                    outcome="PROPOSED",
                    endpoint_id=endpoint.id,
                    agent_uuid=endpoint.agent_uuid,
                    hostname=endpoint.hostname,
                    evidence_json=metrics,
                )
            elif prev_anomalies:
                record_decision_log(
                    db,
                    actor_source="ONLINE_AGENT",
                    decision_type="HEALTH_CHECK",
                    rule_or_model="TelemetryWatchdog",
                    action_taken="verified_healthy",
                    why_explanation=(
                        f"Endpoint '{endpoint.hostname}' transitioned back to healthy operational state "
                        f"(score {metrics['health_score']}/100, previously: {'; '.join(prev_anomalies)})."
                    ),
                    observed_state=f"IP={metrics.get('ip_address')}, GW_RTT={metrics.get('gateway_latency_ms')}ms, Health={metrics['health_score']}/100",
                    expected_state="All network & service checks passing",
                    confidence=1.0,
                    outcome="RESOLVED",
                    endpoint_id=endpoint.id,
                    agent_uuid=endpoint.agent_uuid,
                    hostname=endpoint.hostname,
                    evidence_json=metrics,
                )

    if req.decision_logs:
        for dl in req.decision_logs:
            record_decision_log(
                db,
                actor_source=str(dl.get("actor_source") or "ONLINE_AGENT"),
                decision_type=str(dl.get("decision_type") or "HEALTH_CHECK"),
                rule_or_model=dl.get("rule_or_model"),
                action_taken=dl.get("action_taken"),
                why_explanation=str(dl.get("why_explanation") or "Agent decision logged."),
                observed_state=dl.get("observed_state"),
                expected_state=dl.get("expected_state"),
                confidence=dl.get("confidence"),
                outcome=str(dl.get("outcome") or "INFO"),
                endpoint_id=endpoint.id,
                agent_uuid=endpoint.agent_uuid,
                hostname=endpoint.hostname,
                evidence_json=dl.get("evidence_json") or {},
            )

    # Check pending tasks ready to dispatch to this LAN agent
    task_stmt = (
        select(AgentTask)
        .where(AgentTask.agent_uuid == req.agent_uuid, AgentTask.status == "PENDING")
        .order_by(AgentTask.created_at.asc())
        .limit(10)
    )
    pending_tasks = (await db.execute(task_stmt)).scalars().all()
    dispatched_list = []
    now_utc = datetime.now(timezone.utc)
    for t in pending_tasks:
        t.status = "DISPATCHED"
        t.dispatched_at = now_utc
        dispatched_list.append({
            "task_uuid": t.task_uuid,
            "tool_id": t.tool_id,
            "arguments": t.arguments_json or {},
            "reason": t.reason,
        })

    await db.commit()
    return {
        "status": "ACK",
        "server_time": datetime.now(timezone.utc),
        "pending_tasks": dispatched_list,
    }


@router.get("/network-info")
async def get_server_network_info(current_user: User = Depends(get_current_user)):
    lan_ips = detect_server_lan_ips()
    primary_ip = lan_ips[0] if lan_ips else "127.0.0.1"
    return {
        "lan_ips": lan_ips,
        "primary_lan_ip": primary_ip,
        "backend_port": settings.PORT,
        "server_url": f"http://{primary_ip}:{settings.PORT}",
        "join_command": f"python agent.py --server http://{primary_ip}:{settings.PORT} daemon",
    }


@router.get("/tasks")
async def list_recent_tasks(
    agent_uuid: Optional[str] = None,
    limit: int = 25,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(AgentTask).order_by(desc(AgentTask.created_at)).limit(min(limit, 100))
    if agent_uuid:
        stmt = stmt.where(AgentTask.agent_uuid == agent_uuid)
    tasks = (await db.execute(stmt)).scalars().all()
    return [_serialize_task(t) for t in tasks]


@router.get("/tasks/{task_uuid}")
async def get_task_status(
    task_uuid: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = (await db.execute(select(AgentTask).where(AgentTask.task_uuid == task_uuid))).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Agent task not found.")
    return _serialize_task(task)


@router.post("/broadcast-task")
async def broadcast_remote_task(
    req: AgentBroadcastTaskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ["technician", "admin"]:
        raise HTTPException(status_code=403, detail="Only technicians and administrators can dispatch remote fleet tasks.")

    clean_args = _validate_remote_tool(req.tool_id, req.arguments)

    stmt = select(Endpoint).order_by(Endpoint.last_seen_at.desc())
    endpoints = (await db.execute(stmt)).scalars().all()
    if req.agent_uuids:
        targets = [ep for ep in endpoints if ep.agent_uuid in req.agent_uuids]
    else:
        targets = [ep for ep in endpoints if ep.status == "ONLINE"]

    if not targets:
        raise HTTPException(status_code=404, detail="No matching ONLINE endpoints available to receive the task.")

    created = []
    for ep in targets:
        task = AgentTask(
            task_uuid=f"task-{uuid.uuid4().hex[:12]}",
            endpoint_id=ep.id,
            agent_uuid=ep.agent_uuid,
            target_hostname=ep.hostname,
            tool_id=req.tool_id,
            arguments_json=clean_args,
            reason=req.reason or f"Fleet LAN broadcast dispatched by {current_user.name}",
            requested_by_user_id=current_user.id,
            requested_by_name=current_user.name,
            status="PENDING",
        )
        db.add(task)
        created.append(task)

    record_decision_log(
        db,
        actor_source="POLICY_ENGINE",
        decision_type="REMOTE_EXECUTED",
        rule_or_model="FleetRemotePolicy",
        action_taken=req.tool_id,
        why_explanation=(
            f"Operator {current_user.name} dispatched allowlisted command '{req.tool_id}' across "
            f"{len(created)} LAN system(s): {', '.join(t.hostname for t in targets)}. "
            f"Reason: {req.reason or 'Network-wide diagnostic/remediation sweep'}."
        ),
        observed_state=f"Targets={len(created)} ({', '.join(t.ip_address or t.hostname for t in targets)})",
        expected_state=f"All targets execute '{req.tool_id}' safely via local daemon",
        confidence=1.0,
        outcome="PROPOSED",
    )

    await db.commit()
    for t in created:
        await db.refresh(t)
    return {"dispatched_count": len(created), "tasks": [_serialize_task(t) for t in created]}


@router.get("", response_model=List[dict])
async def list_agents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Endpoint).order_by(Endpoint.last_seen_at.desc())
    endpoints = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": ep.id,
            "agent_uuid": ep.agent_uuid,
            "hostname": ep.hostname,
            "os_name": ep.os_name,
            "os_version": ep.os_version,
            "agent_version": ep.agent_version,
            "ip_address": ep.ip_address,
            "adapter_name": ep.adapter_name,
            "mac_address": ep.mac_address,
            "last_telemetry": ep.last_telemetry_json,
            "last_seen_at": ep.last_seen_at,
            "status": ep.status,
        }
        for ep in endpoints
    ]


@router.post("/{agent_uuid}/tasks")
async def create_agent_task(
    agent_uuid: str,
    req: AgentTaskCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ["technician", "admin"]:
        raise HTTPException(status_code=403, detail="Only technicians and administrators can execute remote system tasks.")

    ep = (await db.execute(select(Endpoint).where(Endpoint.agent_uuid == agent_uuid))).scalar_one_or_none()
    if not ep:
        raise HTTPException(status_code=404, detail="Endpoint agent not found.")

    clean_args = _validate_remote_tool(req.tool_id, req.arguments)

    task = AgentTask(
        task_uuid=f"task-{uuid.uuid4().hex[:12]}",
        endpoint_id=ep.id,
        agent_uuid=ep.agent_uuid,
        target_hostname=ep.hostname,
        tool_id=req.tool_id,
        arguments_json=clean_args,
        reason=req.reason or f"Initiated from Monitoring Console by {current_user.name}",
        requested_by_user_id=current_user.id,
        requested_by_name=current_user.name,
        status="PENDING",
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return _serialize_task(task)


@router.get("/{agent_uuid}/tasks/pending")
async def get_pending_agent_tasks(agent_uuid: str, db: AsyncSession = Depends(get_db)):
    ep = (await db.execute(select(Endpoint).where(Endpoint.agent_uuid == agent_uuid))).scalar_one_or_none()
    if not ep:
        raise HTTPException(status_code=404, detail="Agent UUID not recognized.")

    ep.last_seen_at = datetime.now(timezone.utc)
    ep.status = "ONLINE"

    stmt = (
        select(AgentTask)
        .where(AgentTask.agent_uuid == agent_uuid, AgentTask.status == "PENDING")
        .order_by(AgentTask.created_at.asc())
        .limit(10)
    )
    tasks = (await db.execute(stmt)).scalars().all()
    now_utc = datetime.now(timezone.utc)
    out = []
    for t in tasks:
        t.status = "DISPATCHED"
        t.dispatched_at = now_utc
        out.append({
            "task_uuid": t.task_uuid,
            "tool_id": t.tool_id,
            "arguments": t.arguments_json or {},
            "reason": t.reason,
        })
    await db.commit()
    return {"tasks": out}


@router.post("/{agent_uuid}/tasks/{task_uuid}/result")
async def submit_agent_task_result(
    agent_uuid: str,
    task_uuid: str,
    req: AgentTaskResultRequest,
    db: AsyncSession = Depends(get_db),
):
    task = (
        await db.execute(select(AgentTask).where(AgentTask.task_uuid == task_uuid, AgentTask.agent_uuid == agent_uuid))
    ).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Agent task not found.")

    ep = (await db.execute(select(Endpoint).where(Endpoint.agent_uuid == agent_uuid))).scalar_one_or_none()

    task.status = req.status.upper() if req.status else "COMPLETED"
    task.result_status = req.result_status
    task.verification_status = req.verification_status
    task.output_text = req.output_text
    task.error_text = req.error_text
    task.result_json = {
        "executed_actions": req.executed_actions or [],
        "why_explanation": req.why_explanation,
    }
    task.completed_at = datetime.now(timezone.utc)

    if ep and req.telemetry:
        _, metrics = record_telemetry_snapshot(
            db,
            endpoint_id=ep.id,
            agent_uuid=ep.agent_uuid,
            hostname=ep.hostname,
            telemetry=req.telemetry,
            source_mode="REMOTE_PROBE",
            fallback_ip=ep.ip_address,
        )
        ep.last_telemetry_json = req.telemetry
        ep.last_seen_at = datetime.now(timezone.utc)
        if metrics.get("ip_address"):
            ep.ip_address = metrics["ip_address"]
        if metrics.get("adapter_name"):
            ep.adapter_name = metrics["adapter_name"]

    why_msg = req.why_explanation or (
        f"Remote LAN task '{task.tool_id}' on '{task.target_hostname}' finished with status={task.status} "
        f"(verification={task.verification_status or 'N/A'})."
    )
    record_decision_log(
        db,
        actor_source="ONLINE_AGENT",
        decision_type="REMOTE_EXECUTED",
        rule_or_model=f"RemoteTask:{task.tool_id}",
        action_taken=task.tool_id,
        why_explanation=why_msg,
        observed_state=req.observed_state or (req.error_text or req.output_text or task.result_status or "")[:240],
        expected_state=req.expected_state or f"{task.tool_id} completed & postcondition verified",
        confidence=1.0 if task.status == "COMPLETED" else 0.4,
        outcome=task.verification_status or task.result_status or task.status,
        endpoint_id=ep.id if ep else task.endpoint_id,
        agent_uuid=agent_uuid,
        hostname=task.target_hostname,
        evidence_json={
            "task_uuid": task.task_uuid,
            "arguments": task.arguments_json,
            "executed_actions": req.executed_actions or [],
            "verification_status": task.verification_status,
        },
    )

    await db.commit()
    return _serialize_task(task)


@router.post("/{agent_uuid}/sync", response_model=AgentSyncBatchResponse)
async def sync_offline_events(
    agent_uuid: str,
    batch: AgentSyncBatchRequest,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Endpoint).where(Endpoint.agent_uuid == agent_uuid)
    endpoint = (await db.execute(stmt)).scalar_one_or_none()
    if not endpoint:
        raise HTTPException(status_code=404, detail="Agent UUID not recognized.")

    accepted: List[str] = []
    rejected: List[str] = []
    duplicate: List[str] = []

    for item in batch.events:
        chk_stmt = select(EndpointSyncEvent).where(EndpointSyncEvent.event_uuid == item.event_uuid)
        existing = (await db.execute(chk_stmt)).scalar_one_or_none()
        if existing:
            duplicate.append(item.event_uuid)
            continue

        try:
            if item.event_type == "INCIDENT_REPORTED":
                p = item.payload or {}
                inc = Incident(
                    incident_number=p.get("incident_number", f"INC-SYNC-{item.event_uuid[:8]}"),
                    reporter_id=p.get("reporter_id", 1),
                    endpoint_id=endpoint.id,
                    title=p.get("title", "Offline Reported Incident"),
                    description=p.get("description", "Reported while endpoint was offline."),
                    category=p.get("category", "NETWORK"),
                    priority=p.get("priority", "MEDIUM"),
                    status=p.get("status", "NEW"),
                    sync_idempotency_key=item.event_uuid,
                )
                db.add(inc)

            elif item.event_type == "DIAGNOSTIC_COLLECTED":
                p = item.payload or {}
                target_inc_id = p.get("incident_id")
                if target_inc_id is not None:
                    inc_exists = (await db.execute(select(Incident.id).where(Incident.id == target_inc_id))).scalar_one_or_none()
                    if inc_exists:
                        run = DiagnosticRun(
                            incident_id=target_inc_id,
                            endpoint_id=endpoint.id,
                            source="AGENT_OFFLINE",
                            status="COMPLETED",
                            summary=p.get("summary") or p.get("outcome_summary", "Offline collected telemetry."),
                            findings_json=p.get("evidence") or p.get("diagnostic_evidence", {}),
                        )
                        db.add(run)

                diag_ev = p.get("diagnostic_evidence") or p.get("evidence")
                if isinstance(diag_ev, dict) and diag_ev:
                    record_telemetry_snapshot(
                        db,
                        endpoint_id=endpoint.id,
                        agent_uuid=endpoint.agent_uuid,
                        hostname=endpoint.hostname,
                        telemetry=diag_ev,
                        source_mode="AGENT_OFFLINE",
                        fallback_ip=endpoint.ip_address,
                    )

                trace = p.get("decision_trace") or {}
                record_decision_log(
                    db,
                    actor_source="OFFLINE_AGENT",
                    decision_type=trace.get("decision_type", "HEALTH_CHECK"),
                    rule_or_model=trace.get("rule_or_model", p.get("rule_matched") or "LocalRuleEngine"),
                    action_taken=trace.get("action_taken", "queue_diagnostics"),
                    why_explanation=trace.get("why_explanation") or p.get("outcome_summary") or "Offline diagnostics collected and queued for sync.",
                    observed_state=trace.get("observed_state"),
                    expected_state=trace.get("expected_state"),
                    confidence=trace.get("confidence"),
                    outcome="INFO",
                    endpoint_id=endpoint.id,
                    agent_uuid=endpoint.agent_uuid,
                    hostname=endpoint.hostname,
                    log_uuid=f"sync-{item.event_uuid[:16]}",
                )

            elif item.event_type == "OFFLINE_REMEDIATION_SUCCESS":
                p = item.payload or {}
                issue = p.get("detected_issue") or "Offline Detected Issue"
                tool = p.get("recommended_action") or "unknown_tool"
                inc = Incident(
                    incident_number=f"INC-FIXED-{item.event_uuid[:8].upper()}",
                    reporter_id=1,
                    endpoint_id=endpoint.id,
                    title=f"[FIXED] {issue}",
                    description=f"Issue detected and remediated offline by agent on {endpoint.hostname}.",
                    category="NETWORK",
                    priority="LOW",
                    status="RESOLVED",
                    diagnosis_summary=f"Offline diagnosis: {issue} (Rule: {p.get('rule_matched', 'N/A')}).",
                    resolution_summary=p.get("outcome_summary", f"[FIXED] Issue successfully fixed and verified via offline tool '{tool}'."),
                    resolved_at=datetime.now(timezone.utc),
                    sync_idempotency_key=item.event_uuid,
                )
                db.add(inc)

                ver_ev = p.get("verification_evidence", {}) or {}
                fresh_ev = ver_ev.get("fresh_evidence") if isinstance(ver_ev, dict) else None
                if isinstance(fresh_ev, dict) and fresh_ev:
                    record_telemetry_snapshot(
                        db,
                        endpoint_id=endpoint.id,
                        agent_uuid=endpoint.agent_uuid,
                        hostname=endpoint.hostname,
                        telemetry=fresh_ev,
                        source_mode="AGENT_OFFLINE",
                        fallback_ip=endpoint.ip_address,
                    )

                trace = p.get("decision_trace") or {}
                record_decision_log(
                    db,
                    actor_source="OFFLINE_AGENT",
                    decision_type=trace.get("decision_type", "AUTO_REMEDIATED"),
                    rule_or_model=trace.get("rule_or_model", p.get("rule_matched") or "KB-LOCAL-RULE"),
                    action_taken=trace.get("action_taken", tool),
                    why_explanation=trace.get("why_explanation") or p.get("outcome_summary") or f"Offline agent detected '{issue}' and automatically remediated via '{tool}'.",
                    observed_state=trace.get("observed_state") or issue,
                    expected_state=trace.get("expected_state") or "Postcondition verified resolved",
                    confidence=trace.get("confidence", 0.95),
                    outcome="FIXED",
                    endpoint_id=endpoint.id,
                    agent_uuid=endpoint.agent_uuid,
                    hostname=endpoint.hostname,
                    evidence_json={"executed_actions": p.get("executed_actions", [])},
                    log_uuid=f"sync-{item.event_uuid[:16]}",
                )

            elif item.event_type in ["OFFLINE_REMEDIATION_FAILED", "OFFLINE_ESCALATION"]:
                p = item.payload or {}
                issue = p.get("detected_issue") or "Offline Issue"
                tool = p.get("recommended_action") or "none"
                inc = Incident(
                    incident_number=f"INC-FLAG-{item.event_uuid[:8].upper()}",
                    reporter_id=1,
                    endpoint_id=endpoint.id,
                    title=f"[FLAGGED] {issue}",
                    description=f"Issue detected offline on {endpoint.hostname}. Automated remediation was unable to resolve the issue or was prohibited by policy.",
                    category="NETWORK",
                    priority="HIGH",
                    status="ESCALATED",
                    diagnosis_summary=f"Offline diagnosis: {issue} (Rule: {p.get('rule_matched', 'N/A')}).",
                    resolution_summary=p.get("outcome_summary", f"[FLAGGED: CANNOT BE DONE AUTOMATICALLY] Remediation tool '{tool}' could not resolve the issue. Flagged for manual technician intervention."),
                    sync_idempotency_key=item.event_uuid,
                )
                db.add(inc)

                trace = p.get("decision_trace") or {}
                record_decision_log(
                    db,
                    actor_source="OFFLINE_AGENT",
                    decision_type=trace.get("decision_type", "ESCALATED"),
                    rule_or_model=trace.get("rule_or_model", p.get("rule_matched") or "KB-LOCAL-RULE"),
                    action_taken=trace.get("action_taken", tool),
                    why_explanation=trace.get("why_explanation") or p.get("outcome_summary") or f"Offline agent flagged '{issue}' for technician intervention.",
                    observed_state=trace.get("observed_state") or issue,
                    expected_state=trace.get("expected_state") or "Autonomous verification or technician resolution",
                    confidence=trace.get("confidence", 0.9),
                    outcome="ESCALATED",
                    endpoint_id=endpoint.id,
                    agent_uuid=endpoint.agent_uuid,
                    hostname=endpoint.hostname,
                    evidence_json={"remediation_result": p.get("remediation_result")},
                    log_uuid=f"sync-{item.event_uuid[:16]}",
                )

            sync_ev = EndpointSyncEvent(
                endpoint_id=endpoint.id,
                event_uuid=item.event_uuid,
                event_type=item.event_type,
                payload_json=item.payload,
                created_at_local=item.created_at_local if item.created_at_local.tzinfo else item.created_at_local.replace(tzinfo=timezone.utc),
                received_at_server=datetime.now(timezone.utc),
                sync_status="ACCEPTED",
            )
            db.add(sync_ev)
            accepted.append(item.event_uuid)

        except Exception:
            rejected.append(item.event_uuid)

    await db.commit()

    return AgentSyncBatchResponse(
        accepted_uuids=accepted,
        rejected_uuids=rejected,
        duplicate_uuids=duplicate,
        server_time=datetime.now(timezone.utc),
    )
