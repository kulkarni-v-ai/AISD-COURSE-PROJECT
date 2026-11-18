from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.db.base import Base


class DiagnosticRun(Base):
    __tablename__ = "diagnostic_runs"

    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False)
    endpoint_id = Column(Integer, ForeignKey("endpoints.id"), nullable=True)
    source = Column(String(32), default="RULE", nullable=False)  # RULE, AI, AGENT, TECHNICIAN
    rule_version = Column(String(32), nullable=True)
    model_name = Column(String(64), nullable=True)
    status = Column(String(32), default="COMPLETED", nullable=False)  # RUNNING, COMPLETED, FAILED
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    completed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    summary = Column(Text, nullable=True)
    findings_json = Column(JSON, nullable=True)

    incident = relationship("Incident", back_populates="diagnostic_runs")
    evidence_items = relationship("DiagnosticEvidence", back_populates="diagnostic_run", cascade="all, delete-orphan")


class DiagnosticEvidence(Base):
    __tablename__ = "diagnostic_evidence"

    id = Column(Integer, primary_key=True, index=True)
    diagnostic_run_id = Column(Integer, ForeignKey("diagnostic_runs.id"), nullable=False)
    evidence_type = Column(String(64), nullable=False)  # network_adapter, ip_config, dns_test, gateway_ping, event_log, service_status
    key = Column(String(128), nullable=False)
    value_json = Column(JSON, nullable=False)
    collected_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    sensitivity = Column(String(32), default="LOW", nullable=False)  # LOW, MEDIUM, HIGH
    redacted = Column(Integer, default=0, nullable=False)

    diagnostic_run = relationship("DiagnosticRun", back_populates="evidence_items")
