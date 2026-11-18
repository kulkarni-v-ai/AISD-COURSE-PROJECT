from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime


class DiagnosticEvidenceCreate(BaseModel):
    evidence_type: str
    key: str
    value_json: Dict[str, Any]
    sensitivity: Optional[str] = "LOW"


class DiagnosticEvidenceResponse(BaseModel):
    id: int
    diagnostic_run_id: int
    evidence_type: str
    key: str
    value_json: Dict[str, Any]
    collected_at: datetime
    sensitivity: str
    redacted: int

    class Config:
        from_attributes = True


class DiagnosticRunResponse(BaseModel):
    id: int
    incident_id: int
    endpoint_id: Optional[int] = None
    source: str
    rule_version: Optional[str] = None
    model_name: Optional[str] = None
    status: str
    started_at: datetime
    completed_at: datetime
    summary: Optional[str] = None
    findings_json: Optional[Dict[str, Any]] = None
    evidence_items: List[DiagnosticEvidenceResponse] = []

    class Config:
        from_attributes = True


class HypothesisItem(BaseModel):
    cause: str
    confidence: float
    evidence_ids: List[str] = []
    missing_evidence: List[str] = []
    next_checks: List[str] = []


class DiagnosisResult(BaseModel):
    status: str = "hypotheses"
    summary: str
    hypotheses: List[HypothesisItem] = []
    recommended_tool_ids: List[str] = []
    requires_technician: bool = False
    sources: List[str] = []
    is_fallback: bool = False
    provider: str = "rule_engine"


class RunDiagnosisRequest(BaseModel):
    use_ai: Optional[bool] = True
    collect_live: Optional[bool] = False
    synthetic_evidence: Optional[Dict[str, Any]] = None
