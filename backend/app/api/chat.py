import json
import logging
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.future import select

from app.core.config import settings
from app.rag.engine import rag_engine, SEED_KB_DOCUMENTS
from app.services.load_balancer import ollama_load_balancer
from app.services.ollama_provider import ollama_provider

logger = logging.getLogger("aisd.chat")

router = APIRouter(prefix="/api/chat", tags=["AI Chatbot"])


class ChatMessageItem(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: Optional[List[ChatMessageItem]] = []
    agent_uuid: Optional[str] = None
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    sources: List[Dict[str, Any]]
    recommended_tools: List[str]
    category: str
    provider: str


def _build_rule_based_reply(query: str, retrieved_docs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generates a structured, grounded IT resolution when LLM is offline or unreachable."""
    q_lower = query.lower()
    tools: List[str] = []
    category = "NETWORK"
    summary_parts = []

    if any(k in q_lower for k in ("169.254", "apipa", "dhcp", "no internet, secured", "lease")):
        tools.append("renew_dhcp")
        category = "NETWORK"
        summary_parts.append(
            "An APIPA / DHCP lease failure was identified. "
            "Execute `renew_dhcp` to release the current invalid IP and negotiate a new lease from the campus DHCP server."
        )
    elif any(k in q_lower for k in ("dns", "resolve", "domain", "nxdomain", "host", "lookup")):
        tools.append("flush_dns_cache")
        category = "NETWORK"
        summary_parts.append(
            "DNS name resolution failure detected. "
            "Execute `flush_dns_cache` to clear stale local resolver caches, followed by `test_dns`."
        )
    elif any(k in q_lower for k in ("printer", "spooler", "print", "cups")):
        tools.append("restart_approved_service")
        category = "PRINTER"
        summary_parts.append(
            "Print spooling daemon stoppage detected. "
            "Execute `restart_approved_service` (service 'Spooler' on Windows or 'cups' on Linux) to restore printing."
        )
    elif any(k in q_lower for k in ("adapter", "disabled", "down", "disconnected")):
        tools.append("enable_adapter")
        category = "NETWORK"
        summary_parts.append(
            "Network interface appears disabled. "
            "Execute `enable_adapter` to bring the interface up."
        )
    elif any(k in q_lower for k in ("gateway", "router", "unreachable", "100% packet loss")):
        tools.extend(["test_gateway", "renew_dhcp"])
        category = "NETWORK"
        summary_parts.append(
            "Default gateway is unreachable. "
            "Verify local link status and execute `renew_dhcp` to re-register the client ARP entry."
        )
    else:
        summary_parts.append(
            "I analyzed your request against the campus IT knowledge base. "
            "Please review the recommended SOP procedures attached below or submit an incident ticket for Level 2 support."
        )

    if retrieved_docs:
        doc_titles = [f"• [{d.get('doc_id')}] {d.get('title')}" for d in retrieved_docs[:3]]
        summary_parts.append("\nRelevant Standard Operating Procedures:\n" + "\n".join(doc_titles))

    return {
        "reply": "\n\n".join(summary_parts),
        "recommended_tools": tools,
        "category": category,
        "provider": "rule_engine (rag_hybrid_fallback)"
    }


@router.post("/message", response_model=ChatResponse)
async def chat_message(req: ChatRequest):
    """
    IT Incident Chatbot endpoint:
    1. Ingests user question.
    2. Performs hybrid dense transformer + BM25 RAG search against knowledge procedures.
    3. Routes to Ollama LLM via Load Balancer (or deterministic fallback if LLM is offline).
    4. Returns grounded answer with cited procedures and recommended tools.
    """
    user_query = req.message.strip()
    if not user_query:
        raise HTTPException(status_code=400, detail="Query message cannot be empty.")

    # Retrieve relevant RAG documentation chunks
    retrieved_chunks = rag_engine.search_local(user_query, SEED_KB_DOCUMENTS, top_k=3)

    # Format context for LLM
    doc_context = "\n\n".join([
        f"Document [{d.get('doc_id')}]: {d.get('title')}\n{d.get('chunk_text')}"
        for d in retrieved_chunks
    ]) if retrieved_chunks else "No specific troubleshooting procedures found."

    allowed_tools = [
        "collect_network_status", "test_gateway", "test_dns",
        "renew_dhcp", "flush_dns_cache", "enable_adapter",
        "get_service_status", "restart_approved_service", "verify_network_connectivity"
    ]

    system_prompt = (
        "You are the AISD AI IT Support Assistant for students, staff, and lab workstations.\n"
        "Your mission is to guide users to diagnose and safely resolve network, printing, and OS issues on Windows and Linux systems.\n"
        "RULES:\n"
        "1. Be helpful, professional, and concise.\n"
        "2. Ground your advice in the provided standard operating procedures (SOPs).\n"
        "3. Explicitly cite Document IDs (e.g. [KB-NET-001], [KB-LNX-001]).\n"
        "4. If recommending automated action, select ONLY from the allowlisted tools:\n"
        f"   {allowed_tools}\n"
        "5. Clearly format your answer with 'Root Cause', 'Recommended Steps', and 'Tool Recommendation'."
    )

    messages = [{"role": "system", "content": system_prompt}]
    for h in (req.history or [])[-4:]:
        messages.append({"role": h.role, "content": h.content})

    user_prompt = (
        f"User Query: {user_query}\n\n"
        f"Retrieved Standard Operating Procedures:\n{doc_context}\n\n"
        "Provide a grounded IT diagnosis and resolution recommendation:"
    )
    messages.append({"role": "user", "content": user_prompt})

    # Check if load balancer has healthy Ollama instances
    try:
        active_model = await ollama_provider._resolve_model()
        data = await ollama_load_balancer.route_chat(
            model=active_model,
            messages=messages,
            format_json=False,
            temperature=0.2,
            timeout=float(settings.OLLAMA_TIMEOUT_SECONDS)
        )
        reply_content = data.get("message", {}).get("content", "").strip()

        # Identify mentioned tools
        recommended_tools = [t for t in allowed_tools if t in reply_content]
        # Infer category
        category = "PRINTER" if any(k in reply_content.lower() for k in ("spooler", "print", "cups")) else "NETWORK"

        return ChatResponse(
            reply=reply_content,
            sources=retrieved_chunks,
            recommended_tools=recommended_tools,
            category=category,
            provider=f"ollama ({active_model} via load-balancer)"
        )
    except Exception as exc:
        logger.info(f"Ollama chat via load balancer unavailable ({exc}). Using intelligent RAG fallback.")
        fallback = _build_rule_based_reply(user_query, retrieved_chunks)
        return ChatResponse(
            reply=fallback["reply"],
            sources=retrieved_chunks,
            recommended_tools=fallback["recommended_tools"],
            category=fallback["category"],
            provider=fallback["provider"]
        )


@router.get("/loadbalancer/status")
async def get_load_balancer_status():
    """Returns live status, latency metrics, and health of all upstream Ollama nodes."""
    return ollama_load_balancer.get_status()


class AddNodeRequest(BaseModel):
    url: str
    name: Optional[str] = None


@router.post("/loadbalancer/nodes")
async def add_load_balancer_node(req: AddNodeRequest):
    """Dynamically registers an additional Ollama instance in the load balancer pool."""
    ollama_load_balancer.add_node(req.url, req.name)
    await ollama_load_balancer.check_all_nodes(timeout=2.0)
    return {
        "status": "success",
        "message": f"Node {req.url} added.",
        "pool": ollama_load_balancer.get_status()
    }
