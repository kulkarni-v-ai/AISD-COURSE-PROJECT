from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.db.base import Base


class RemediationPlan(Base):
    __tablename__ = "remediation_plans"

    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False)
    diagnostic_run_id = Column(Integer, ForeignKey("diagnostic_runs.id"), nullable=True)
    tool_id = Column(String(64), nullable=False)  # Predefined registered tool ID
    arguments_json = Column(JSON, default=dict, nullable=False)
    reason = Column(Text, nullable=False)
    risk_level = Column(String(16), default="R1", nullable=False)  # R0, R1, R2, R3
    approval_required = Column(Integer, default=0, nullable=False)  # 0: Auto-approved, 1: Requires technician approval
    status = Column(String(32), default="PENDING", nullable=False)  # PENDING, APPROVED, REJECTED, EXECUTING, COMPLETED, FAILED
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    incident = relationship("Incident", back_populates="remediation_plans")
    approval = relationship("Approval", back_populates="remediation_plan", uselist=False, cascade="all, delete-orphan")
    execution = relationship("RemediationExecution", back_populates="remediation_plan", uselist=False, cascade="all, delete-orphan")


class Approval(Base):
    __tablename__ = "approvals"

    id = Column(Integer, primary_key=True, index=True)
    remediation_plan_id = Column(Integer, ForeignKey("remediation_plans.id"), nullable=False)
    approver_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    decision = Column(String(32), nullable=False)  # APPROVED, REJECTED
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    remediation_plan = relationship("RemediationPlan", back_populates="approval")
    approver = relationship("User")


class RemediationExecution(Base):
    __tablename__ = "remediation_executions"

    id = Column(Integer, primary_key=True, index=True)
    remediation_plan_id = Column(Integer, ForeignKey("remediation_plans.id"), nullable=False)
    endpoint_id = Column(Integer, ForeignKey("endpoints.id"), nullable=True)
    tool_id = Column(String(64), nullable=False)
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    execution_status = Column(String(32), default="RUNNING", nullable=False)  # RUNNING, SUCCESS, FAILED
    exit_code = Column(Integer, nullable=True)
    output_redacted = Column(Text, nullable=True)
    error_redacted = Column(Text, nullable=True)
    is_mock = Column(Integer, default=1, nullable=False)

    remediation_plan = relationship("RemediationPlan", back_populates="execution")
    verification = relationship("VerificationResult", back_populates="execution", uselist=False, cascade="all, delete-orphan")


class VerificationResult(Base):
    __tablename__ = "verification_results"

    id = Column(Integer, primary_key=True, index=True)
    execution_id = Column(Integer, ForeignKey("remediation_executions.id"), nullable=False)
    verification_type = Column(String(64), nullable=False)  # gateway_ping, ip_validity, service_running, dns_resolve
    status = Column(String(32), nullable=False)  # VERIFIED_RESOLVED, NOT_RESOLVED, INCONCLUSIVE, VERIFICATION_ERROR
    evidence_json = Column(JSON, nullable=True)
    verified_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    execution = relationship("RemediationExecution", back_populates="verification")
