from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, JSON
from sqlalchemy.orm import relationship
from app.db.base import Base


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id = Column(Integer, primary_key=True, index=True)
    doc_id = Column(String(64), unique=True, index=True, nullable=False)  # e.g., KB-NET-001
    title = Column(String(255), nullable=False)
    source_type = Column(String(64), default="SOP", nullable=False)  # SOP, TROUBLESHOOTING_GUIDE, INCIDENT_RESOLUTION
    category = Column(String(64), default="NETWORK", nullable=False)
    version = Column(String(32), default="1.0", nullable=False)
    approved = Column(Boolean, default=True, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    chunks = relationship("KnowledgeChunk", back_populates="document", cascade="all, delete-orphan")


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("knowledge_documents.id"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    chunk_text = Column(Text, nullable=False)
    embedding_json = Column(JSON, nullable=True)  # Stored embedding vector for cosine similarity retrieval
    metadata_json = Column(JSON, nullable=True)

    document = relationship("KnowledgeDocument", back_populates="chunks")
