from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime


class AgentEnrollRequest(BaseModel):
    agent_uuid: str
    hostname: str
    os_name: str = "Windows"
    os_version: str
    agent_version: str = "1.0.0"
    ip_address: Optional[str] = None
    adapter_name: Optional[str] = None
    mac_address: Optional[str] = None
    telemetry: Optional[Dict[str, Any]] = None


class AgentEnrollResponse(BaseModel):
    endpoint_id: int
    agent_uuid: str
    status: str
    message: str


class AgentHeartbeatRequest(BaseModel):
    agent_uuid: str
    status: Optional[str] = "ONLINE"
    ip_address: Optional[str] = None
    adapter_name: Optional[str] = None
    mac_address: Optional[str] = None
    telemetry: Optional[Dict[str, Any]] = None
    decision_logs: Optional[List[Dict[str, Any]]] = None


class AgentTaskCreateRequest(BaseModel):
    tool_id: str
    arguments: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None


class AgentBroadcastTaskRequest(BaseModel):
    tool_id: str
    arguments: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None
    agent_uuids: Optional[List[str]] = None


class AgentTaskResultRequest(BaseModel):
    status: str  # COMPLETED, FAILED
    result_status: Optional[str] = None
    verification_status: Optional[str] = None
    output_text: Optional[str] = ""
    error_text: Optional[str] = ""
    why_explanation: Optional[str] = None
    observed_state: Optional[str] = None
    expected_state: Optional[str] = None
    telemetry: Optional[Dict[str, Any]] = None
    executed_actions: Optional[List[Dict[str, Any]]] = None


class SyncEventItem(BaseModel):
    event_uuid: str
    event_type: str  # INCIDENT_REPORTED, DIAGNOSTIC_COLLECTED, ACTION_EXECUTED
    payload: Dict[str, Any]
    created_at_local: datetime


class AgentSyncBatchRequest(BaseModel):
    agent_uuid: str
    events: List[SyncEventItem]


class AgentSyncBatchResponse(BaseModel):
    accepted_uuids: List[str]
    rejected_uuids: List[str]
    duplicate_uuids: List[str]
    server_time: datetime
