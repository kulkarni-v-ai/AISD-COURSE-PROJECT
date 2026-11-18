from datetime import datetime, timezone
import random
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc

from app.db.session import get_db
from app.models.incident import Incident, IncidentComment
from app.models.user import User
from app.models.endpoint import Endpoint
from app.models.audit import AuditEvent
from app.schemas.incident import (
    IncidentCreate, IncidentUpdate, IncidentResponse, IncidentAssign,
    IncidentStatusUpdate, IncidentCommentCreate, IncidentCommentResponse
)
from app.api.deps import get_current_user

router = APIRouter(prefix="/incidents", tags=["Incidents"])


def generate_incident_number() -> str:
    now_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    rand_suffix = random.randint(1000, 9999)
    return f"INC-{now_str}-{rand_suffix}"


VALID_TRANSITIONS = {
    "NEW": ["TRIAGED", "DIAGNOSING", "CANCELLED"],
    "TRIAGED": ["DIAGNOSING", "ACTION_PLANNED", "CANCELLED"],
    "DIAGNOSING": ["ACTION_PLANNED", "APPROVAL_REQUIRED", "ESCALATED", "FAILED"],
    "ACTION_PLANNED": ["APPROVAL_REQUIRED", "REMEDIATING", "ESCALATED"],
    "APPROVAL_REQUIRED": ["REMEDIATING", "ESCALATED", "CANCELLED"],
    "REMEDIATING": ["VERIFYING", "FAILED", "ESCALATED"],
    "VERIFYING": ["RESOLVED", "DIAGNOSING", "ESCALATED", "FAILED"],
    "ESCALATED": ["DIAGNOSING", "ACTION_PLANNED", "RESOLVED", "CANCELLED"],
    "FAILED": ["DIAGNOSING", "ESCALATED", "CANCELLED"],
    "RESOLVED": ["NEW"],  # Can reopen
    "CANCELLED": []
}


@router.post("", response_model=IncidentResponse)
async def create_incident(
    incident_in: IncidentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Check sync idempotency key if provided
    if incident_in.sync_idempotency_key:
        stmt = select(Incident).where(Incident.sync_idempotency_key == incident_in.sync_idempotency_key)
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing:
            return existing

    inc_num = generate_incident_number()
    incident = Incident(
        incident_number=inc_num,
        reporter_id=current_user.id,
        endpoint_id=incident_in.endpoint_id,
        title=incident_in.title.strip(),
        description=incident_in.description.strip(),
        category=incident_in.category.upper() if incident_in.category else "NETWORK",
        priority=incident_in.priority.upper() if incident_in.priority else "MEDIUM",
        status="NEW",
        sync_idempotency_key=incident_in.sync_idempotency_key
    )
    db.add(incident)
    await db.flush()

    # Initial comment
    comment = IncidentComment(
        incident_id=incident.id,
        author_id=current_user.id,
        author_name=current_user.name,
        comment=f"Incident opened: {incident.title}",
        is_internal=0
    )
    db.add(comment)

    # Audit event
    audit = AuditEvent(
        actor_type="USER",
        actor_id=str(current_user.id),
        event_type="INCIDENT_CREATED",
        entity_type="INCIDENT",
        entity_id=str(incident.id),
        details_json={
            "incident_number": incident.incident_number,
            "title": incident.title,
            "priority": incident.priority,
            "category": incident.category
        }
    )
    db.add(audit)

    await db.commit()
    await db.refresh(incident)

    res = IncidentResponse.model_validate(incident)
    res.reporter_name = current_user.name
    return res


@router.get("", response_model=List[IncidentResponse])
async def list_incidents(
    status: Optional[str] = None,
    category: Optional[str] = None,
    priority: Optional[str] = None,
    assigned: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = select(Incident).order_by(desc(Incident.created_at))

    # Role enforcement: Students/Faculty only see their own tickets
    if current_user.role in ["student", "faculty"]:
        query = query.where(Incident.reporter_id == current_user.id)

    if status:
        query = query.where(Incident.status == status.upper())
    if category:
        query = query.where(Incident.category == category.upper())
    if priority:
        query = query.where(Incident.priority == priority.upper())
    if assigned is True:
        query = query.where(Incident.assigned_technician_id.isnot(None))
    elif assigned is False:
        query = query.where(Incident.assigned_technician_id.is_(None))

    result = await db.execute(query)
    incidents = result.scalars().all()

    # Enrich with names
    enriched = []
    for inc in incidents:
        item = IncidentResponse.model_validate(inc)
        if inc.reporter_id:
            rep = await db.get(User, inc.reporter_id)
            if rep:
                item.reporter_name = rep.name
        if inc.assigned_technician_id:
            tech = await db.get(User, inc.assigned_technician_id)
            if tech:
                item.assigned_technician_name = tech.name
        if inc.endpoint_id:
            ep = await db.get(Endpoint, inc.endpoint_id)
            if ep:
                item.endpoint_hostname = ep.hostname
        enriched.append(item)

    return enriched


@router.get("/{incident_id}", response_model=IncidentResponse)
async def get_incident(
    incident_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    stmt = select(Incident).where(Incident.id == incident_id)
    incident = (await db.execute(stmt)).scalar_one_or_none()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found.")

    if current_user.role in ["student", "faculty"] and incident.reporter_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied to this incident.")

    item = IncidentResponse.model_validate(incident)
    if incident.reporter_id:
        rep = await db.get(User, incident.reporter_id)
        if rep:
            item.reporter_name = rep.name
    if incident.assigned_technician_id:
        tech = await db.get(User, incident.assigned_technician_id)
        if tech:
            item.assigned_technician_name = tech.name
    if incident.endpoint_id:
        ep = await db.get(Endpoint, incident.endpoint_id)
        if ep:
            item.endpoint_hostname = ep.hostname

    return item


@router.patch("/{incident_id}", response_model=IncidentResponse)
async def update_incident(
    incident_id: int,
    update_in: IncidentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    incident = await db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found.")

    if current_user.role in ["student", "faculty"] and incident.reporter_id != current_user.id:
        raise HTTPException(status_code=403, detail="Cannot edit this incident.")

    if update_in.title is not None:
        incident.title = update_in.title.strip()
    if update_in.description is not None:
        incident.description = update_in.description.strip()
    if update_in.category is not None:
        incident.category = update_in.category.upper()
    if update_in.priority is not None:
        incident.priority = update_in.priority.upper()
    if update_in.diagnosis_summary is not None:
        incident.diagnosis_summary = update_in.diagnosis_summary
    if update_in.resolution_summary is not None:
        incident.resolution_summary = update_in.resolution_summary

    incident.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(incident)

    return await get_incident(incident_id, db, current_user)


@router.post("/{incident_id}/assign", response_model=IncidentResponse)
async def assign_incident(
    incident_id: int,
    assign_in: IncidentAssign,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in ["technician", "admin"]:
        raise HTTPException(status_code=403, detail="Only technicians or admins can assign incidents.")

    incident = await db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found.")

    tech = await db.get(User, assign_in.technician_id)
    if not tech or tech.role not in ["technician", "admin"]:
        raise HTTPException(status_code=400, detail="Assigned user must be a technician or admin.")

    old_tech = incident.assigned_technician_id
    incident.assigned_technician_id = tech.id
    if incident.status == "NEW":
        incident.status = "TRIAGED"
    incident.updated_at = datetime.now(timezone.utc)

    # Add comment
    comment = IncidentComment(
        incident_id=incident.id,
        author_id=current_user.id,
        author_name=current_user.name,
        comment=f"Incident assigned to {tech.name}.",
        is_internal=1
    )
    db.add(comment)

    audit = AuditEvent(
        actor_type="USER",
        actor_id=str(current_user.id),
        event_type="INCIDENT_ASSIGNED",
        entity_type="INCIDENT",
        entity_id=str(incident.id),
        details_json={"from_technician": old_tech, "to_technician": tech.id}
    )
    db.add(audit)

    await db.commit()
    return await get_incident(incident_id, db, current_user)


@router.post("/{incident_id}/status", response_model=IncidentResponse)
async def update_status(
    incident_id: int,
    status_in: IncidentStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    incident = await db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found.")

    target_status = status_in.status.upper()
    current_status = incident.status

    # Validate status transition
    allowed = VALID_TRANSITIONS.get(current_status, [])
    if target_status not in allowed and target_status != current_status and current_user.role != "admin":
        raise HTTPException(
            status_code=400,
            detail=f"Invalid transition from {current_status} to {target_status}. Allowed transitions: {allowed}"
        )

    # Disallow direct jump to RESOLVED without verification unless admin
    if target_status == "RESOLVED" and current_user.role != "admin" and current_status != "VERIFYING":
        raise HTTPException(
            status_code=400,
            detail="Cannot mark incident RESOLVED directly without completing verification step."
        )

    incident.status = target_status
    incident.updated_at = datetime.now(timezone.utc)
    if target_status == "RESOLVED":
        incident.resolved_at = datetime.now(timezone.utc)

    comment = IncidentComment(
        incident_id=incident.id,
        author_id=current_user.id,
        author_name=current_user.name,
        comment=f"Status changed from {current_status} to {target_status}. {status_in.notes or ''}".strip(),
        is_internal=0
    )
    db.add(comment)

    audit = AuditEvent(
        actor_type="USER",
        actor_id=str(current_user.id),
        event_type="INCIDENT_STATUS_CHANGED",
        entity_type="INCIDENT",
        entity_id=str(incident.id),
        details_json={"from": current_status, "to": target_status, "notes": status_in.notes}
    )
    db.add(audit)

    await db.commit()
    return await get_incident(incident_id, db, current_user)


@router.post("/{incident_id}/escalate", response_model=IncidentResponse)
async def escalate_incident(
    incident_id: int,
    reason: Optional[str] = "Automated remediation unsuccessful or required manual inspection.",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    incident = await db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found.")

    incident.status = "ESCALATED"
    incident.priority = "HIGH" if incident.priority in ["LOW", "MEDIUM"] else "CRITICAL"
    incident.updated_at = datetime.now(timezone.utc)

    comment = IncidentComment(
        incident_id=incident.id,
        author_id=current_user.id,
        author_name=current_user.name,
        comment=f"Incident ESCALATED to Level 2 Technician. Reason: {reason}",
        is_internal=1
    )
    db.add(comment)

    audit = AuditEvent(
        actor_type="SYSTEM",
        actor_id=str(current_user.id),
        event_type="INCIDENT_ESCALATED",
        entity_type="INCIDENT",
        entity_id=str(incident.id),
        details_json={"reason": reason}
    )
    db.add(audit)

    await db.commit()
    return await get_incident(incident_id, db, current_user)


@router.get("/{incident_id}/comments", response_model=List[IncidentCommentResponse])
async def list_comments(
    incident_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    incident = await db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found.")

    query = select(IncidentComment).where(IncidentComment.incident_id == incident_id).order_by(IncidentComment.created_at)
    if current_user.role in ["student", "faculty"]:
        query = query.where(IncidentComment.is_internal == 0)

    comments = (await db.execute(query)).scalars().all()
    return [IncidentCommentResponse.model_validate(c) for c in comments]


@router.post("/{incident_id}/comments", response_model=IncidentCommentResponse)
async def add_comment(
    incident_id: int,
    comment_in: IncidentCommentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    incident = await db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found.")

    is_int = 1 if (comment_in.is_internal and current_user.role in ["technician", "admin"]) else 0
    comment = IncidentComment(
        incident_id=incident.id,
        author_id=current_user.id,
        author_name=current_user.name,
        comment=comment_in.comment.strip(),
        is_internal=is_int
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)
    return IncidentCommentResponse.model_validate(comment)
