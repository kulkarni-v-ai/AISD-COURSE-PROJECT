from datetime import datetime, timezone
from sqlalchemy import Column, Integer, Float, String, Text, DateTime, ForeignKey, JSON
from app.db.base import Base


class EndpointTelemetrySnapshot(Base):
    __tablename__ = "endpoint_telemetry_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    endpoint_id = Column(Integer, ForeignKey("endpoints.id"), nullable=False, index=True)
    agent_uuid = Column(String(64), nullable=False, index=True)
    hostname = Column(String(128), nullable=False)
    ip_address = Column(String(64), nullable=True)
    adapter_name = Column(String(128), nullable=True)
    adapter_status = Column(String(32), nullable=True)

    dhcp_enabled = Column(Integer, nullable=True)  # 1/0/None
    dns_dhcp_enabled = Column(Integer, nullable=True)
    static_dns_configured = Column(Integer, default=0, nullable=False)

    gateway_ip = Column(String(64), nullable=True)
    gateway_reachable = Column(Integer, nullable=True)
    gateway_latency_ms = Column(Float, nullable=True)
    gateway_loss_pct = Column(Integer, default=0, nullable=False)

    internet_reachable = Column(Integer, nullable=True)
    internet_latency_ms = Column(Float, nullable=True)
    internet_loss_pct = Column(Integer, default=0, nullable=False)

    dns_resolved = Column(Integer, nullable=True)
    services_running_count = Column(Integer, default=0, nullable=False)
    services_total_count = Column(Integer, default=4, nullable=False)

    health_score = Column(Integer, default=100, nullable=False)
    anomaly_count = Column(Integer, default=0, nullable=False)
    source_mode = Column(String(32), default="AGENT_ONLINE", nullable=False)
    telemetry_json = Column(JSON, default=dict, nullable=False)
    recorded_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)


class AgentTask(Base):
    __tablename__ = "agent_tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_uuid = Column(String(64), unique=True, index=True, nullable=False)
    endpoint_id = Column(Integer, ForeignKey("endpoints.id"), nullable=False, index=True)
    agent_uuid = Column(String(64), nullable=False, index=True)
    target_hostname = Column(String(128), nullable=False)

    tool_id = Column(String(64), nullable=False)
    arguments_json = Column(JSON, default=dict, nullable=False)
    reason = Column(Text, nullable=True)
    requested_by_user_id = Column(Integer, nullable=True)
    requested_by_name = Column(String(128), nullable=True)

    status = Column(String(32), default="PENDING", nullable=False, index=True)  # PENDING, DISPATCHED, COMPLETED, FAILED, REJECTED
    result_status = Column(String(32), nullable=True)
    verification_status = Column(String(32), nullable=True)
    output_text = Column(Text, nullable=True)
    error_text = Column(Text, nullable=True)
    result_json = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    dispatched_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class AgentDecisionLog(Base):
    __tablename__ = "agent_decision_logs"

    id = Column(Integer, primary_key=True, index=True)
    log_uuid = Column(String(64), unique=True, index=True, nullable=False)
    endpoint_id = Column(Integer, ForeignKey("endpoints.id"), nullable=True, index=True)
    agent_uuid = Column(String(64), nullable=True, index=True)
    hostname = Column(String(128), nullable=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=True)

    actor_source = Column(String(32), default="RULE_ENGINE", nullable=False)  # OFFLINE_AGENT, ONLINE_AGENT, RULE_ENGINE, OLLAMA_AI, REMEDIATION_ENGINE, POLICY_ENGINE
    decision_type = Column(String(32), default="RULE_DIAGNOSIS", nullable=False)  # AUTO_REMEDIATED, REMOTE_EXECUTED, AI_HYPOTHESIS, RULE_DIAGNOSIS, ESCALATED, POLICY_BLOCKED, COOLDOWN_SKIP, HEALTH_CHECK
    rule_or_model = Column(String(128), nullable=True)
    action_taken = Column(String(128), nullable=True)

    why_explanation = Column(Text, nullable=False)
    observed_state = Column(String(256), nullable=True)
    expected_state = Column(String(256), nullable=True)
    confidence = Column(Float, nullable=True)
    outcome = Column(String(32), default="INFO", nullable=False)
    evidence_json = Column(JSON, default=dict, nullable=False)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
