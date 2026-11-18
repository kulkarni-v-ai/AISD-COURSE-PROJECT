from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.db.base import Base


class EndpointSyncEvent(Base):
    __tablename__ = "endpoint_sync_events"

    id = Column(Integer, primary_key=True, index=True)
    endpoint_id = Column(Integer, ForeignKey("endpoints.id"), nullable=False)
    event_uuid = Column(String(64), unique=True, index=True, nullable=False)
    event_type = Column(String(64), nullable=False)  # INCIDENT_REPORTED, DIAGNOSTIC_COLLECTED, ACTION_EXECUTED
    payload_json = Column(JSON, nullable=False)
    created_at_local = Column(DateTime(timezone=True), nullable=False)
    received_at_server = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    sync_status = Column(String(32), default="ACCEPTED", nullable=False)  # ACCEPTED, REJECTED, DUPLICATE

    endpoint = relationship("Endpoint", back_populates="sync_events")
