from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.models.incident import Incident, IncidentComment
from app.models.remediation import RemediationPlan, Approval, RemediationExecution, VerificationResult
from app.models.audit import AuditEvent
from app.models.user import User
from app.schemas.remediation import (
    RemediationPlanCreate, RemediationPlanResponse, ApprovalDecisionRequest,
    ApprovalResponse, RemediationExecutionResponse, VerificationResultResponse
)
from app.api.deps import get_current_user
from app.remediation.policy import policy_engine
from app.remediation.executor import remediation_executor
from app.services.decision_logger import record_decision_log

router = APIRouter(tags=["Remediation"])


@router.post("/incidents/{incident_id}/remediation-plan", response_model=RemediationPlanResponse)
async def create_remediation_plan(
    incident_id: int,
    plan_in: RemediationPlanCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    incident = await db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found.")

    args = plan_in.arguments or {}
    is_allowed, reason, tool_def, approval_req = policy_engine.evaluate_plan_creation(
        tool_id=plan_in.tool_id,
        arguments=args,
        user_role=current_user.role
    )

    if not is_allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Remediation policy rejected tool '{plan_in.tool_id}': {reason}"
        )

    plan = RemediationPlan(
        incident_id=incident.id,
        tool_id=plan_in.tool_id,
        arguments_json=args,
        reason=plan_in.reason,
        risk_level=tool_def.risk_level,
        approval_required=1 if approval_req else 0,
        status="PENDING" if approval_req else "APPROVED"
    )
    db.add(plan)

    incident.status = "APPROVAL_REQUIRED" if approval_req else "ACTION_PLANNED"
    incident.updated_at = datetime.now(timezone.utc)

    comment = IncidentComment(
        incident_id=incident.id,
        author_id=current_user.id,
        author_name=current_user.name,
        comment=f"Remediation Plan created for tool '{tool_def.name}' (Risk: {tool_def.risk_level}). {'Requires technician approval before execution.' if approval_req else 'Pre-approved under policy.'}",
        is_internal=0
    )
    db.add(comment)

    audit = AuditEvent(
        actor_type="USER",
        actor_id=str(current_user.id),
        event_type="REMEDIATION_PLAN_CREATED",
        entity_type="REMEDIATION_PLAN",
        entity_id=f"plan_{plan_in.tool_id}",
        details_json={
            "incident_id": incident.id,
            "tool_id": plan_in.tool_id,
            "risk_level": tool_def.risk_level,
            "approval_required": approval_req
        }
    )
    db.add(audit)

    await db.commit()
    
    # Eagerly load plan with relationships to prevent async lazy loading error
    stmt = (
        select(RemediationPlan)
        .where(RemediationPlan.id == plan.id)
        .options(
            selectinload(RemediationPlan.approval),
            selectinload(RemediationPlan.execution)
        )
    )
    loaded_plan = (await db.execute(stmt)).scalar_one()
    return loaded_plan


@router.get("/incidents/{incident_id}/remediation-plans", response_model=List[RemediationPlanResponse])
async def list_incident_plans(
    incident_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    stmt = (
        select(RemediationPlan)
        .where(RemediationPlan.incident_id == incident_id)
        .options(
            selectinload(RemediationPlan.approval),
            selectinload(RemediationPlan.execution).selectinload(RemediationExecution.verification)
        )
        .order_by(RemediationPlan.created_at.desc())
    )
    plans = (await db.execute(stmt)).scalars().all()
    return plans


@router.post("/remediation-plans/{plan_id}/approve", response_model=ApprovalResponse)
async def approve_plan(
    plan_id: int,
    decision_in: ApprovalDecisionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in ["technician", "admin"]:
        raise HTTPException(status_code=403, detail="Only technicians and administrators can approve remediation plans.")

    plan = await db.get(RemediationPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Remediation plan not found.")

    decision_clean = decision_in.decision.upper()
    if decision_clean not in ["APPROVED", "REJECTED"]:
        raise HTTPException(status_code=400, detail="Decision must be 'APPROVED' or 'REJECTED'.")

    approval = Approval(
        remediation_plan_id=plan.id,
        approver_user_id=current_user.id,
        decision=decision_clean,
        reason=decision_in.reason
    )
    db.add(approval)

    plan.status = decision_clean
    incident = await db.get(Incident, plan.incident_id)
    if incident:
        if decision_clean == "APPROVED":
            incident.status = "ACTION_PLANNED"
        else:
            incident.status = "ESCALATED"
        incident.updated_at = datetime.now(timezone.utc)

        comment = IncidentComment(
            incident_id=incident.id,
            author_id=current_user.id,
            author_name=current_user.name,
            comment=f"Remediation plan for tool '{plan.tool_id}' was {decision_clean} by {current_user.name}. Reason: {decision_in.reason or 'None provided.'}",
            is_internal=1
        )
        db.add(comment)

    audit = AuditEvent(
        actor_type="USER",
        actor_id=str(current_user.id),
        event_type=f"REMEDIATION_{decision_clean}",
        entity_type="REMEDIATION_PLAN",
        entity_id=str(plan.id),
        details_json={"decision": decision_clean, "reason": decision_in.reason}
    )
    db.add(audit)

    record_decision_log(
        db,
        actor_source="POLICY_ENGINE",
        decision_type="POLICY_BLOCKED" if decision_clean == "REJECTED" else "RULE_DIAGNOSIS",
        rule_or_model=f"HumanApprovalGate:{plan.risk_level}",
        action_taken=plan.tool_id,
        why_explanation=(
            f"Technician {current_user.name} {decision_clean} Remediation Plan #{plan.id} "
            f"(tool='{plan.tool_id}', risk={plan.risk_level}) for Incident #"
            f"{incident.incident_number if incident else plan.incident_id}. "
            f"Reason: {decision_in.reason or 'Standard technician review'}."
        ),
        observed_state=f"PlanStatus={decision_clean}",
        expected_state="Verified technician authorization prior to execution",
        confidence=1.0,
        outcome="PROPOSED" if decision_clean == "APPROVED" else "REJECTED",
        endpoint_id=incident.endpoint_id if incident else None,
        incident_id=plan.incident_id,
        evidence_json={"plan_id": plan.id, "decision": decision_clean},
    )

    await db.commit()
    await db.refresh(approval)

    resp = ApprovalResponse.model_validate(approval)
    resp.approver_name = current_user.name
    return resp


@router.post("/remediation-plans/{plan_id}/execute", response_model=RemediationExecutionResponse)
async def execute_plan(
    plan_id: int,
    is_mock: Optional[bool] = None,
    simulate_verification_outcome: Optional[str] = "VERIFIED_RESOLVED",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    stmt = (
        select(RemediationPlan)
        .where(RemediationPlan.id == plan_id)
        .options(selectinload(RemediationPlan.approval))
    )
    plan = (await db.execute(stmt)).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Remediation plan not found.")

    incident = await db.get(Incident, plan.incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found.")

    # Check execution authorization with policy engine
    approval_status = plan.approval.decision if plan.approval else ("APPROVED" if plan.approval_required == 0 else "PENDING")
    can_exec, reason = policy_engine.can_execute(
        tool_id=plan.tool_id,
        approval_status=approval_status,
        approval_required=bool(plan.approval_required),
        user_role=current_user.role
    )

    if not can_exec:
        raise HTTPException(status_code=403, detail=f"Execution prohibited: {reason}")

    # Mark executing
    incident.status = "REMEDIATING"
    plan.status = "EXECUTING"
    await db.commit()

    # Execute tool and postcondition verification
    exec_status, exit_code, out_str, err_str, v_status, v_evidence = await remediation_executor.execute(
        tool_id=plan.tool_id,
        arguments=plan.arguments_json,
        is_mock=is_mock,
        simulate_outcome=simulate_verification_outcome or "VERIFIED_RESOLVED"
    )

    # Store execution record
    execution = RemediationExecution(
        remediation_plan_id=plan.id,
        endpoint_id=incident.endpoint_id,
        tool_id=plan.tool_id,
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        execution_status=exec_status,
        exit_code=exit_code,
        output_redacted=out_str,
        error_redacted=err_str,
        is_mock=1 if (is_mock is not False) else 0
    )
    db.add(execution)
    await db.flush()

    # Store verification result
    verification = VerificationResult(
        execution_id=execution.id,
        verification_type=plan.tool_id,
        status=v_status,
        evidence_json=v_evidence,
        verified_at=datetime.now(timezone.utc)
    )
    db.add(verification)

    plan.status = "COMPLETED" if exec_status == "SUCCESS" else "FAILED"

    # Strict Rule: Only mark resolved if verification supports it!
    if v_status == "VERIFIED_RESOLVED":
        incident.status = "RESOLVED"
        incident.resolved_at = datetime.now(timezone.utc)
        incident.resolution_summary = f"[FIXED] Issue verified resolved via tool '{plan.tool_id}'. Post-action verification confirmed operational state."
    else:
        incident.status = "ESCALATED"
        incident.resolution_summary = f"[FLAGGED: CANNOT BE DONE AUTOMATICALLY] Remediation tool '{plan.tool_id}' was executed, but post-action verification failed ({v_status}). Flagged for manual technician intervention."

    incident.updated_at = datetime.now(timezone.utc)

    # Comments & Audit
    comment_text = (
        f"[FIXED] Action '{plan.tool_id}' completed successfully and postcondition verified. Incident state marked as FIXED."
        if v_status == "VERIFIED_RESOLVED" else
        f"[FLAGGED: CANNOT BE DONE AUTOMATICALLY] Action '{plan.tool_id}' execution status: {exec_status}, verification result: {v_status}. Flagged for manual technician escalation."
    )
    comment = IncidentComment(
        incident_id=incident.id,
        author_id=current_user.id,
        author_name=f"AISD Remediation Engine [{ 'MOCK' if execution.is_mock else 'REAL' }]",
        comment=comment_text,
        is_internal=0
    )
    db.add(comment)

    audit = AuditEvent(
        actor_type="SYSTEM",
        actor_id=str(current_user.id),
        event_type="REMEDIATION_EXECUTED",
        entity_type="REMEDIATION_EXECUTION",
        entity_id=str(execution.id),
        details_json={
            "tool_id": plan.tool_id,
            "status": exec_status,
            "verification_status": v_status,
            "is_mock": bool(execution.is_mock)
        }
    )
    db.add(audit)

    record_decision_log(
        db,
        actor_source="REMEDIATION_ENGINE",
        decision_type="AUTO_REMEDIATED" if v_status == "VERIFIED_RESOLVED" else "ESCALATED",
        rule_or_model=f"Policy:{plan.risk_level} ({'Mock' if execution.is_mock else 'Live Windows'})",
        action_taken=plan.tool_id,
        why_explanation=(
            f"Executed approved plan #{plan.id} tool '{plan.tool_id}' for Incident #{incident.incident_number} "
            f"(reason: {plan.reason}). Execution exited {exit_code} ({exec_status}) and postcondition verification "
            f"returned '{v_status}'."
        ),
        observed_state=v_evidence.get("reason") or v_evidence.get("dns_check") or f"exec={exec_status}, verify={v_status}",
        expected_state=f"Postcondition verified operational for {plan.tool_id}",
        confidence=1.0 if v_status == "VERIFIED_RESOLVED" else 0.4,
        outcome="FIXED" if v_status == "VERIFIED_RESOLVED" else "ESCALATED",
        endpoint_id=incident.endpoint_id,
        incident_id=incident.id,
        evidence_json={"execution_id": execution.id, "verification": v_evidence},
    )

    await db.commit()

    return RemediationExecutionResponse(
        id=execution.id,
        remediation_plan_id=execution.remediation_plan_id,
        endpoint_id=execution.endpoint_id,
        tool_id=execution.tool_id,
        started_at=execution.started_at,
        completed_at=execution.completed_at,
        execution_status=execution.execution_status,
        exit_code=execution.exit_code,
        output_redacted=execution.output_redacted,
        error_redacted=execution.error_redacted,
        is_mock=execution.is_mock,
        verification=VerificationResultResponse.model_validate(verification)
    )


@router.get("/remediation-plans/{plan_id}/verification", response_model=Optional[VerificationResultResponse])
async def get_verification(
    plan_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    stmt = (
        select(VerificationResult)
        .join(RemediationExecution)
        .where(RemediationExecution.remediation_plan_id == plan_id)
    )
    result = (await db.execute(stmt)).scalar_one_or_none()
    if not result:
        raise HTTPException(status_code=404, detail="No verification record found for this plan.")
    return result
