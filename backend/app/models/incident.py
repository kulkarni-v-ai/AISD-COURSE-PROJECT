from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from app.db.base import Base


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    incident_number = Column(String(32), unique=True, index=True, nullable=False)
    reporter_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    endpoint_id = Column(Integer, ForeignKey("endpoints.id"), nullable=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    category = Column(String(64), default="NETWORK", nullable=False)  # NETWORK, HARDWARE, SOFTWARE, PRINTER, ACCOUNT, OTHER
    priority = Column(String(32), default="MEDIUM", nullable=False)  # LOW, MEDIUM, HIGH, CRITICAL
    status = Column(String(32), default="NEW", nullable=False)
    # Statuses: NEW -> TRIAGED -> DIAGNOSING -> ACTION_PLANNED -> APPROVAL_REQUIRED -> REMEDIATING -> VERIFYING -> RESOLVED | ESCALATED | FAILED | CANCELLED
    assigned_technician_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    diagnosis_summary = Column(Text, nullable=True)
    resolution_summary = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    sync_idempotency_key = Column(String(64), unique=True, nullable=True, index=True)

    # Relationships
    reporter = relationship("User", back_populates="reported_incidents", foreign_keys=[reporter_id])
    assignee = relationship("User", back_populates="assigned_incidents", foreign_keys=[assigned_technician_id])
    endpoint = relationship("Endpoint", back_populates="incidents")
    diagnostic_runs = relationship("DiagnosticRun", back_populates="incident", cascade="all, delete-orphan")
    remediation_plans = relationship("RemediationPlan", back_populates="incident", cascade="all, delete-orphan")
    comments = relationship("IncidentComment", back_populates="incident", cascade="all, delete-orphan")


class IncidentComment(Base):
    __tablename__ = "incident_comments"

    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    author_name = Column(String(128), default="System", nullable=False)
    comment = Column(Text, nullable=False)
    is_internal = Column(Integer, default=0, nullable=False)  # 0: public to user, 1: technician only
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    incident = relationship("Incident", back_populates="comments")
