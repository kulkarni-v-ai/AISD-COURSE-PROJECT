from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime


class KnowledgeDocumentCreate(BaseModel):
    doc_id: str
    title: str
    source_type: str = "SOP"
    category: str = "NETWORK"
    version: str = "1.0"
    content: str


class KnowledgeDocumentResponse(BaseModel):
    id: int
    doc_id: str
    title: str
    source_type: str
    category: str
    version: str
    approved: bool
    created_at: datetime
    chunk_count: Optional[int] = 0

    class Config:
        from_attributes = True


class KnowledgeSearchResult(BaseModel):
    doc_id: str
    title: str
    category: str
    chunk_text: str
    similarity_score: float
    source_type: str
