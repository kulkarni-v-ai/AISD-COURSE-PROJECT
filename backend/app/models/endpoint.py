from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.db.base import Base


class Endpoint(Base):
    __tablename__ = "endpoints"

    id = Column(Integer, primary_key=True, index=True)
    agent_uuid = Column(String(64), unique=True, index=True, nullable=False)
    hostname = Column(String(128), nullable=False)
    os_name = Column(String(64), default="Windows", nullable=False)
    os_version = Column(String(64), nullable=False)
    agent_version = Column(String(32), default="1.0.0", nullable=False)
    ip_address = Column(String(64), nullable=True)
    adapter_name = Column(String(128), nullable=True)
    mac_address = Column(String(64), nullable=True)
    last_telemetry_json = Column(JSON, nullable=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    last_seen_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    status = Column(String(32), default="ONLINE", nullable=False)  # ONLINE, OFFLINE, DEGRADED
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    incidents = relationship("Incident", back_populates="endpoint")
    sync_events = relationship("EndpointSyncEvent", back_populates="endpoint")
