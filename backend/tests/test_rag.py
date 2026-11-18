import pytest
from app.rag.engine import rag_engine, SEED_KB_DOCUMENTS


def test_chunking():
    sample_text = (
        "Paragraph 1 explains Wi-Fi issues.\n\n"
        "Paragraph 2 discusses DHCP failure.\n\n"
        "Paragraph 3 covers gateway unreachable."
    )
    chunks = rag_engine.chunk_document(sample_text)
    assert len(chunks) >= 1
    assert any("DHCP" in c for c in chunks)


def test_local_rag_search():
    docs_payload = [
        {
            "doc_id": d["doc_id"],
            "title": d["title"],
            "category": d["category"],
            "source_type": d["source_type"],
            "chunks": [{"chunk_text": d["content"]}]
        }
        for d in SEED_KB_DOCUMENTS
    ]

    query = "Student cannot access anything on college Wi-Fi, 169.254 address"
    results = rag_engine.search_local(query=query, documents=docs_payload, top_k=2)

    assert len(results) > 0
    top_doc = results[0]
    assert top_doc["doc_id"] == "KB-NET-001"
    assert "DHCP" in top_doc["title"] or "Wi-Fi" in top_doc["title"]
    assert top_doc["similarity_score"] > 0.0
