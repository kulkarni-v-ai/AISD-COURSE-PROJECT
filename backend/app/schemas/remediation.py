from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime


class RemediationPlanCreate(BaseModel):
    tool_id: str
    arguments: Optional[Dict[str, Any]] = None
    reason: str


class ApprovalDecisionRequest(BaseModel):
    decision: str  # APPROVED or REJECTED
    reason: Optional[str] = None


class VerificationResultResponse(BaseModel):
    id: int
    execution_id: int
    verification_type: str
    status: str
    evidence_json: Optional[Dict[str, Any]] = None
    verified_at: datetime

    class Config:
        from_attributes = True


class RemediationExecutionResponse(BaseModel):
    id: int
    remediation_plan_id: int
    endpoint_id: Optional[int]
    tool_id: str
    started_at: datetime
    completed_at: Optional[datetime]
    execution_status: str
    exit_code: Optional[int]
    output_redacted: Optional[str]
    error_redacted: Optional[str]
    is_mock: int
    verification: Optional[VerificationResultResponse] = None

    class Config:
        from_attributes = True


class ApprovalResponse(BaseModel):
    id: int
    remediation_plan_id: int
    approver_user_id: int
    approver_name: Optional[str] = None
    decision: str
    reason: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class RemediationPlanResponse(BaseModel):
    id: int
    incident_id: int
    diagnostic_run_id: Optional[int]
    tool_id: str
    arguments_json: Dict[str, Any]
    reason: str
    risk_level: str
    approval_required: int
    status: str
    created_at: datetime
    approval: Optional[ApprovalResponse] = None
    execution: Optional[RemediationExecutionResponse] = None

    class Config:
        from_attributes = True
