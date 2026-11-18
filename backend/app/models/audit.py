from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, JSON
from app.db.base import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True, index=True)
    actor_type = Column(String(32), default="SYSTEM", nullable=False)  # USER, AGENT, AI, RULE, SYSTEM
    actor_id = Column(String(64), nullable=True)
    event_type = Column(String(64), nullable=False)  # INCIDENT_CREATED, DIAGNOSTIC_RUN, REMEDIATION_EXECUTED, etc.
    entity_type = Column(String(32), nullable=False)  # INCIDENT, REMEDIATION_PLAN, ENDPOINT, USER
    entity_id = Column(String(64), nullable=False)
    details_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
