from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.models.knowledge import KnowledgeDocument, KnowledgeChunk
from app.models.user import User
from app.schemas.knowledge import (
    KnowledgeDocumentCreate, KnowledgeDocumentResponse, KnowledgeSearchResult
)
from app.api.deps import get_current_user
from app.rag.engine import rag_engine

router = APIRouter(prefix="/knowledge", tags=["Knowledge Base & RAG"])


@router.get("/documents", response_model=List[KnowledgeDocumentResponse])
async def list_documents(
    category: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = select(KnowledgeDocument).options(selectinload(KnowledgeDocument.chunks))
    if category:
        query = query.where(KnowledgeDocument.category == category.upper())
    result = await db.execute(query)
    docs = result.scalars().all()

    enriched = []
    for d in docs:
        item = KnowledgeDocumentResponse.model_validate(d)
        item.chunk_count = len(d.chunks)
        enriched.append(item)
    return enriched


@router.post("/documents", response_model=KnowledgeDocumentResponse)
async def create_document(
    doc_in: KnowledgeDocumentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in ["technician", "admin"]:
        raise HTTPException(status_code=403, detail="Only technicians and administrators can add approved knowledge documents.")

    stmt = select(KnowledgeDocument).where(KnowledgeDocument.doc_id == doc_in.doc_id.strip())
    if (await db.execute(stmt)).scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Document with ID '{doc_in.doc_id}' already exists.")

    doc = KnowledgeDocument(
        doc_id=doc_in.doc_id.strip(),
        title=doc_in.title.strip(),
        source_type=doc_in.source_type.upper(),
        category=doc_in.category.upper(),
        version=doc_in.version,
        approved=True,
        content=doc_in.content.strip()
    )
    db.add(doc)
    await db.flush()

    # Chunk and store
    chunks = rag_engine.chunk_document(doc_in.content)
    for idx, c_text in enumerate(chunks):
        chunk = KnowledgeChunk(
            document_id=doc.id,
            chunk_index=idx,
            chunk_text=c_text,
            metadata_json={"doc_id": doc.doc_id, "category": doc.category}
        )
        db.add(chunk)

    await db.commit()
    await db.refresh(doc)

    item = KnowledgeDocumentResponse.model_validate(doc)
    item.chunk_count = len(chunks)
    return item


@router.get("/search", response_model=List[KnowledgeSearchResult])
async def search_knowledge(
    q: str = Query(..., min_length=2, description="Search query"),
    top_k: int = Query(3, ge=1, le=10),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    stmt = select(KnowledgeDocument).options(selectinload(KnowledgeDocument.chunks))
    docs = (await db.execute(stmt)).scalars().all()

    payload = [
        {
            "doc_id": d.doc_id,
            "title": d.title,
            "category": d.category,
            "source_type": d.source_type,
            "chunks": [{"chunk_text": c.chunk_text} for c in d.chunks] if d.chunks else [{"chunk_text": d.content}]
        }
        for d in docs
    ]

    results = rag_engine.search_local(query=q, documents=payload, top_k=top_k)
    return [KnowledgeSearchResult(**r) for r in results]
