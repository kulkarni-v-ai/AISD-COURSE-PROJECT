from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime


class IncidentCreate(BaseModel):
    title: str
    description: str
    category: Optional[str] = "NETWORK"  # NETWORK, HARDWARE, SOFTWARE, PRINTER, ACCOUNT, OTHER
    priority: Optional[str] = "MEDIUM"  # LOW, MEDIUM, HIGH, CRITICAL
    endpoint_id: Optional[int] = None
    location: Optional[str] = None
    sync_idempotency_key: Optional[str] = None


class IncidentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    assigned_technician_id: Optional[int] = None
    diagnosis_summary: Optional[str] = None
    resolution_summary: Optional[str] = None


class IncidentAssign(BaseModel):
    technician_id: int


class IncidentStatusUpdate(BaseModel):
    status: str
    notes: Optional[str] = None


class IncidentCommentCreate(BaseModel):
    comment: str
    is_internal: Optional[bool] = False


class IncidentCommentResponse(BaseModel):
    id: int
    incident_id: int
    author_id: Optional[int]
    author_name: str
    comment: str
    is_internal: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class IncidentResponse(BaseModel):
    id: int
    incident_number: str
    reporter_id: int
    reporter_name: Optional[str] = None
    endpoint_id: Optional[int] = None
    endpoint_hostname: Optional[str] = None
    title: str
    description: str
    category: str
    priority: str
    status: str
    assigned_technician_id: Optional[int] = None
    assigned_technician_name: Optional[str] = None
    diagnosis_summary: Optional[str] = None
    resolution_summary: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime] = None
    sync_idempotency_key: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)
