import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.services.load_balancer import OllamaLoadBalancer, OllamaNode
from app.rag.engine import rag_engine, TransformerEmbeddingService, SEED_KB_DOCUMENTS


@pytest.mark.asyncio
async def test_ollama_load_balancer_routing_and_failover():
    """Verify load balancer node management, strategy selection, and health tracking."""
    lb = OllamaLoadBalancer(node_urls=["http://10.0.0.1:11434", "http://10.0.0.2:11434"], strategy="least_connections")
    assert len(lb.nodes) == 2
    assert lb.strategy == "least_connections"

    # Simulate node 1 having 3 active requests, node 2 having 0
    lb.nodes[0].active_requests = 3
    lb.nodes[1].active_requests = 0

    selected = await lb.select_node()
    assert selected is not None
    assert selected.url == "http://10.0.0.2:11434"

    # Simulate node 2 failure
    lb.nodes[1].is_healthy = False
    selected_after_failure = await lb.select_node()
    assert selected_after_failure.url == "http://10.0.0.1:11434"

    # Test status payload
    status = lb.get_status()
    assert status["total_nodes"] == 2
    assert status["healthy_nodes"] == 1


def test_transformer_embedding_and_similarity():
    """Verify dense 384-dimensional semantic embedding generation and math."""
    embedder = TransformerEmbeddingService()
    vec1 = embedder.embed_text("DHCP lease failed with APIPA address 169.254")
    vec2 = embedder.embed_text("APIPA link-local IP address assigned by network")
    vec3 = embedder.embed_text("Cooking recipes for Italian pizza dough")

    assert len(vec1) == 384
    assert len(vec2) == 384
    assert len(vec3) == 384

    from app.rag.engine import dense_cosine_similarity
    sim_related = dense_cosine_similarity(vec1, vec2)
    sim_unrelated = dense_cosine_similarity(vec1, vec3)

    # Related IT terms should have significantly higher semantic similarity than pizza recipes
    assert sim_related > sim_unrelated


def test_rag_hybrid_retrieval_linux_and_windows():
    """Verify RAG hybrid search retrieves both Windows and Linux SOPs based on queries."""
    # Test Windows DHCP query
    win_res = rag_engine.search_local("169.254 APIPA DHCP failure", SEED_KB_DOCUMENTS, top_k=2)
    assert len(win_res) > 0
    doc_ids = [d["doc_id"] for d in win_res]
    assert "KB-NET-001" in doc_ids or "KB-LNX-001" in doc_ids

    # Test Linux CUPS printer query
    lnx_res = rag_engine.search_local("Linux CUPS print daemon failure cups.service", SEED_KB_DOCUMENTS, top_k=2)
    assert len(lnx_res) > 0
    assert any("KB-LNX-003" in d["doc_id"] or "KB-PRT-001" in d["doc_id"] for d in lnx_res)


@pytest.mark.asyncio
async def test_chatbot_api_message_endpoint():
    """Verify POST /api/chat/message returns grounded answers with citations and tool recommendations."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "message": "My computer has an IP address of 169.254.12.34 and no internet",
            "history": []
        }
        res = await client.post("/api/chat/message", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert "reply" in data
        assert "sources" in data
        assert "renew_dhcp" in data.get("recommended_tools", [])
        assert len(data["sources"]) > 0


@pytest.mark.asyncio
async def test_load_balancer_status_endpoint():
    """Verify GET /api/chat/loadbalancer/status returns metrics."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/chat/loadbalancer/status")
        assert res.status_code == 200
        data = res.json()
        assert "strategy" in data
        assert "total_nodes" in data
        assert "nodes" in data
