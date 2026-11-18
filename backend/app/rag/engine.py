import hashlib
import math
import re
import json
from typing import List, Dict, Any, Optional, Tuple
import httpx
from app.core.config import settings

# Attempt to import sentence_transformers if installed in environment
try:
    from sentence_transformers import SentenceTransformer
    _SENTENCE_TRANSFORMER_AVAILABLE = True
except Exception:
    SentenceTransformer = None
    _SENTENCE_TRANSFORMER_AVAILABLE = False


def simple_tokenize(text: str) -> List[str]:
    return re.findall(r"\b[a-zA-Z0-9_\-\.]{2,}\b", text.lower())


def compute_tf(text: str) -> Dict[str, float]:
    tokens = simple_tokenize(text)
    if not tokens:
        return {}
    tf: Dict[str, float] = {}
    for tok in tokens:
        tf[tok] = tf.get(tok, 0.0) + 1.0
    total = float(len(tokens))
    return {k: v / total for k, v in tf.items()}


def cosine_similarity(v1: Dict[str, float], v2: Dict[str, float]) -> float:
    common_keys = set(v1.keys()) & set(v2.keys())
    if not common_keys:
        return 0.0
    dot = sum(v1[k] * v2[k] for k in common_keys)
    norm1 = math.sqrt(sum(v * v for v in v1.values()))
    norm2 = math.sqrt(sum(v * v for v in v2.values()))
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return dot / (norm1 * norm2)


def dense_cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Computes cosine similarity between two dense float vectors."""
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0
    dot = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (norm1 * norm2)))


class TransformerEmbeddingService:
    """
    Local Transformer embedding provider.
    Uses sentence-transformers ('all-MiniLM-L6-v2') when available,
    or a fast 384-dimensional dense semantic hashing projection when running in zero-dependency mode.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None
        if _SENTENCE_TRANSFORMER_AVAILABLE and SentenceTransformer is not None:
            try:
                self._model = SentenceTransformer(model_name)
            except Exception:
                self._model = None

    def embed_text(self, text: str) -> List[float]:
        """Embed text to a 384-dimensional dense float vector."""
        if self._model is not None:
            try:
                vec = self._model.encode(text, convert_to_numpy=True).tolist()
                return [round(float(x), 5) for x in vec]
            except Exception:
                pass

        # Native dense 384-dimensional projection fallback
        dim = 384
        vec = [0.0] * dim
        tokens = simple_tokenize(text)
        if not tokens:
            return vec

        for idx, token in enumerate(tokens):
            weight = 1.0 / (1.0 + 0.05 * math.log(1 + idx))
            # Distribute token semantic energy across 6 feature slots
            for seed in range(6):
                h = int(hashlib.md5(f"{token}:{seed}".encode()).hexdigest(), 16)
                slot = h % dim
                sign = 1.0 if ((h >> 16) & 1) == 0 else -1.0
                vec[slot] += sign * weight

        # L2 normalization
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [round(x / norm, 5) for x in vec]
        return vec


class RAGEngine:
    """
    RAG Engine supporting Hybrid Retrieval (Dense Transformer Vectors + BM25 Lexical overlap)
    and Ollama / Load Balancer vector embeddings.
    """

    def __init__(self):
        self.ollama_base_url = settings.OLLAMA_BASE_URL
        self.embed_model = settings.OLLAMA_EMBED_MODEL
        self.transformer_embedder = TransformerEmbeddingService()

    async def get_embedding(self, text: str) -> Optional[List[float]]:
        """Try to fetch embedding from local Ollama via Load Balancer or fallback to Transformer embedder."""
        try:
            from app.services.load_balancer import ollama_load_balancer
            res = await ollama_load_balancer.route_embeddings(self.embed_model, text)
            if res:
                return res
        except Exception:
            pass

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{self.ollama_base_url}/api/embeddings",
                    json={"model": self.embed_model, "prompt": text}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("embedding")
        except Exception:
            pass

        # Fallback to local transformer embedder
        return self.transformer_embedder.embed_text(text)

    def chunk_document(self, text: str, chunk_size: int = 400, overlap: int = 50) -> List[str]:
        paragraphs = text.split("\n\n")
        chunks = []
        current_chunk = []
        current_len = 0

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            words = para.split()
            if current_len + len(words) > chunk_size and current_chunk:
                chunks.append(" ".join(current_chunk))
                current_chunk = []
                current_len = 0
            current_chunk.append(para)
            current_len += len(words)

        if current_chunk:
            chunks.append(" ".join(current_chunk))
        return chunks if chunks else [text]

    def search_local(self, query: str, documents: List[Dict[str, Any]], top_k: int = 3) -> List[Dict[str, Any]]:
        """
        Hybrid search combining Dense Transformer Embeddings (60%) with
        lexical Term-Frequency / BM25 matching (40%).
        """
        query_tf = compute_tf(query)
        query_dense = self.transformer_embedder.embed_text(query)
        scored = []

        for doc in documents:
            doc_id = doc.get("doc_id", "")
            title = doc.get("title", "")
            category = doc.get("category", "")
            chunks = doc.get("chunks", [])
            if not chunks and "content" in doc:
                chunks = [{"chunk_text": c} for c in self.chunk_document(doc["content"])]

            for chunk in chunks:
                chunk_text = chunk.get("chunk_text", "")
                full_text = f"{title} {category} {chunk_text}"

                # 1. Lexical overlap score
                chunk_tf = compute_tf(full_text)
                lexical_score = cosine_similarity(query_tf, chunk_tf)

                # 2. Dense transformer vector score
                chunk_dense = self.transformer_embedder.embed_text(full_text)
                dense_score = dense_cosine_similarity(query_dense, chunk_dense)
                # Scale dense_score from [-1, 1] to [0, 1]
                dense_norm = max(0.0, (dense_score + 1.0) / 2.0)

                # Hybrid fusion score
                hybrid_score = round(0.4 * lexical_score + 0.6 * dense_norm, 4)

                if hybrid_score > 0.05 or lexical_score > 0.02:
                    scored.append({
                        "doc_id": doc_id,
                        "title": title,
                        "category": category,
                        "chunk_text": chunk_text,
                        "similarity_score": hybrid_score,
                        "lexical_score": round(lexical_score, 4),
                        "dense_score": round(dense_norm, 4),
                        "source_type": doc.get("source_type", "SOP")
                    })

        scored.sort(key=lambda x: x["similarity_score"], reverse=True)
        return scored[:top_k]


rag_engine = RAGEngine()

# Demonstration Knowledge Base Procedures (Cross-Platform: Windows + Linux)
SEED_KB_DOCUMENTS = [
    {
        "doc_id": "KB-NET-001",
        "title": "College Wi-Fi & DHCP Lease Failure Recovery SOP",
        "source_type": "SOP",
        "category": "NETWORK",
        "version": "1.2",
        "content": """SOP-NET-001: Troubleshooting DHCP Lease and APIPA 169.254.x.x Addresses on Campus Wi-Fi.
Symptoms:
1. Student laptop connects to 'Campus-Student-WiFi' with 'No Internet, secured'.
2. IP address starts with 169.254.x.x (APIPA) and default gateway is missing or empty.
Root Cause:
The local DHCP client was unable to contact the college DHCP server or the lease expired while switching access points.
Resolution Procedure:
1. Verify the wireless adapter is physically active and connected to SSID 'Campus-Student-WiFi'.
2. Execute tool `renew_dhcp` (ipconfig /release && ipconfig /renew) to re-initiate DHCP negotiation.
3. Verify that a valid 10.x.x.x or 172.16.x.x IP address is assigned with a valid gateway.
4. Verify gateway ping reachability using `test_gateway`.
Rollback / Escalation:
If the address remains 169.254.x.x after renewal, inspect Access Point DHCP scope exhaustion or escalate to Level 2 Network Operations."""
    },
    {
        "doc_id": "KB-NET-002",
        "title": "Default Gateway Unreachable Troubleshooting Guide",
        "source_type": "TROUBLESHOOTING_GUIDE",
        "category": "NETWORK",
        "version": "1.0",
        "content": """SOP-NET-002: Default Gateway Unreachable on Subnet.
Symptoms:
1. Valid IP address configured, but ping to local default gateway fails with 100% packet loss.
2. Cannot reach internal campus servers or external websites.
Root Cause:
ARP cache corruption, local switch port isolation, or wireless roaming disconnect.
Resolution Procedure:
1. Run diagnostic tool `test_gateway` to verify reachability.
2. Run tool `renew_dhcp` to trigger an ARP flush and re-register MAC on the access point.
3. Test gateway reachability again.
4. If still unreachable, verify whether other clients on the same AP are experiencing issues."""
    },
    {
        "doc_id": "KB-NET-003",
        "title": "Campus DNS Resolution Failure Remediation",
        "source_type": "SOP",
        "category": "NETWORK",
        "version": "1.1",
        "content": """SOP-NET-003: Campus DNS Resolution Failures.
Symptoms:
1. Ping by IP (e.g. 8.8.8.8 or gateway) succeeds, but domain lookups (intranet.college.edu, google.com) time out or return NXDOMAIN.
Root Cause:
Stale DNS client cache or unresponsive local caching resolver.
Resolution Procedure:
1. Execute tool `flush_dns_cache` (Clear-DnsClientCache / ipconfig /flushdns on Windows; resolvectl flush-caches on Linux).
2. Execute tool `test_dns` to query college intranet and external domains.
3. Verify name resolution returns valid records."""
    },
    {
        "doc_id": "KB-NET-004",
        "title": "Network Adapter Disabled or Disconnected SOP",
        "source_type": "SOP",
        "category": "NETWORK",
        "version": "1.0",
        "content": """SOP-NET-004: Network Adapter Disabled or Hardware Disconnected.
Symptoms:
1. Wi-Fi adapter or Ethernet adapter status is 'Disabled' or 'Down'.
2. Network icon shows disconnected globe or red X.
Resolution:
1. Execute tool `enable_adapter` with adapter name.
2. Wait 5 seconds for link training and state transition to 'Up'.
3. Verify adapter state using `collect_network_status`."""
    },
    {
        "doc_id": "KB-NET-005",
        "title": "Campus Wi-Fi Captive Portal Authentication",
        "source_type": "TROUBLESHOOTING_GUIDE",
        "category": "NETWORK",
        "version": "1.0",
        "content": """SOP-NET-005: Wi-Fi Captive Portal Authentication Redirection.
Symptoms:
1. Connected to Wi-Fi, valid IP obtained, but all HTTP traffic redirects to login.college.edu.
Resolution:
1. Ensure student navigates to http://neverssl.com or college portal to trigger authentication screen.
2. Verify credentials with IT Helpdesk if user account is locked."""
    },
    {
        "doc_id": "KB-PRT-001",
        "title": "Windows Print Spooler Service Stoppage Recovery SOP",
        "source_type": "SOP",
        "category": "PRINTER",
        "version": "1.0",
        "content": """SOP-PRT-001: Print Spooler Service Stoppage Recovery.
Symptoms:
1. Lab workstation unable to print; printers missing from Devices & Printers.
2. Windows service 'Spooler' is in STOPPED or ERROR state.
Resolution Procedure:
1. Verify service state with `get_service_status` for service 'Spooler'.
2. Execute tool `restart_approved_service` with service_name='Spooler'.
3. Run postcondition check: verify 'Spooler' is RUNNING.
4. If service crashes immediately upon start, clear corrupt files in C:\\Windows\\System32\\spool\\PRINTERS."""
    },
    {
        "doc_id": "KB-NET-006",
        "title": "Network Cable Disconnected & Wi-Fi Link Lost SOP",
        "source_type": "SOP",
        "category": "NETWORK",
        "version": "1.0",
        "content": """SOP-NET-006: Physical Media Disconnection / Wi-Fi Disconnected.
Symptoms:
1. Network adapter status reports 'Disconnected' or MediaConnectionState=2.
2. System has no connection to local switch, router, or wireless access point.
Root Cause:
Ethernet cable unseated, wall-jack patch cable failure, or wireless radio out of range.
Resolution Procedure:
1. Inspect physical RJ45 cable and switch port link light.
2. If on Wi-Fi, verify SSID is in range and re-authenticate.
3. Verify adapter state returns to 'Up'."""
    },
    {
        "doc_id": "KB-NET-007",
        "title": "Internet WAN Outage (Local LAN Functional) Guide",
        "source_type": "TROUBLESHOOTING_GUIDE",
        "category": "NETWORK",
        "version": "1.0",
        "content": """SOP-NET-007: Internet Outage with Functional Local Subnet.
Symptoms:
1. Local gateway (router) is pingable and internal peers respond.
2. External public IP addresses (e.g. 8.8.8.8) and internet websites fail with 100% packet loss.
Root Cause:
ISP fiber cut, router WAN interface down, or upstream campus firewall block.
Resolution Procedure:
1. Verify local gateway ping with `test_gateway`.
2. Confirm outage is external (WAN-side) and not workstation configuration.
3. Escalate immediately to ISP / Campus Network Operations."""
    },
    {
        "doc_id": "KB-NET-008",
        "title": "Windows Defender Firewall Port & Profile Blocking SOP",
        "source_type": "SOP",
        "category": "SECURITY",
        "version": "1.0",
        "content": """SOP-NET-008: Windows Defender Firewall Blocking Communication.
Symptoms:
1. ICMP ping works between endpoints, but application TCP/HTTP traffic on port 8000 fails.
2. Network profile is set to 'Public' instead of 'Private' / 'Domain'.
Resolution Procedure:
1. Check active firewall profile: `Get-NetFirewallProfile`.
2. Verify inbound rule allows Python/AISD agent: `Get-NetFirewallRule -DisplayName '*AISD*'`.
3. Add allowlist rule for application port if required."""
    },
    {
        "doc_id": "KB-NET-009",
        "title": "Multiple Active Network Adapters & Interface Conflict SOP",
        "source_type": "SOP",
        "category": "NETWORK",
        "version": "1.0",
        "content": """SOP-NET-009: Multiple Network Interfaces Active Concurrently.
Symptoms:
1. Both Wi-Fi and Ethernet (or VPN adapter) are simultaneously connected with conflicting default gateways.
2. Packets route out of suboptimal interface or cause split-tunnel drops.
Resolution Procedure:
1. Identify primary physical interface using `Get-NetAdapter`.
2. Run `flush_dns_cache` to clear multi-homed stale resolver cache.
3. Disconnect redundant secondary interface or adjust interface metrics."""
    },
    {
        "doc_id": "KB-NET-010",
        "title": "High Latency & Packet Loss Remediation Guide",
        "source_type": "TROUBLESHOOTING_GUIDE",
        "category": "NETWORK",
        "version": "1.0",
        "content": """SOP-NET-010: High Network Latency (>5000ms) or Packet Loss (>20%).
Symptoms:
1. Intermittent connectivity, SSH/HTTP timeouts, slow file transfers.
2. ICMP ping reports packet loss between 20% and 90% or response times > 5000ms.
Root Cause:
Wi-Fi co-channel interference, weak signal RSSI, or switch port duplex mismatch.
Resolution Procedure:
1. Run `renew_dhcp` to re-associate with closest campus Access Point.
2. Measure ping latency to default gateway.
3. If packet loss persists, move closer to AP or switch to 5GHz band."""
    },
    # Linux-Specific SOPs
    {
        "doc_id": "KB-LNX-001",
        "title": "Linux NetworkManager & DHCP Recovery SOP",
        "source_type": "SOP",
        "category": "NETWORK",
        "version": "1.0",
        "content": """SOP-LNX-001: Linux Network Interface & DHCP Lease Failure Recovery.
Symptoms:
1. Linux workstation or VM has no IP or an APIPA 169.254.x.x link-local address on eth0 / wlan0.
2. Default route missing from `ip route`.
Resolution Procedure:
1. Execute tool `renew_dhcp` (nmcli device reapply <iface> or dhclient -r && dhclient <iface>).
2. Check `ip addr show` to confirm valid IP assignment.
3. Run postcondition check: verify gateway is pingable."""
    },
    {
        "doc_id": "KB-LNX-002",
        "title": "Linux systemd-resolved DNS Failure Remediation",
        "source_type": "SOP",
        "category": "NETWORK",
        "version": "1.0",
        "content": """SOP-LNX-002: Linux systemd-resolved DNS Cache & Name Resolution Failure.
Symptoms:
1. Linux client pings 8.8.8.8 successfully, but host intranet.college.edu fails to resolve.
2. systemd-resolved cache contains stale NXDOMAIN or timeout records.
Resolution Procedure:
1. Execute tool `flush_dns_cache` (resolvectl flush-caches or systemctl restart systemd-resolved).
2. Verify with `resolvectl status` or `test_dns`.
3. Confirm intranet domain name resolves correctly."""
    },
    {
        "doc_id": "KB-LNX-003",
        "title": "Linux CUPS Printing Service Recovery SOP",
        "source_type": "SOP",
        "category": "PRINTER",
        "version": "1.0",
        "content": """SOP-LNX-003: Linux CUPS Print Daemon Failure Recovery.
Symptoms:
1. Lab workstation unable to submit print jobs; CUPS server error: 'Connection refused'.
2. cups.service or cups-browsed is inactive (dead) or failed.
Resolution Procedure:
1. Verify service status: `systemctl is-active cups`.
2. Execute tool `restart_approved_service` with service_name='cups'.
3. Run postcondition verification to confirm cups.service is active (running)."""
    },
    {
        "doc_id": "KB-LNX-004",
        "title": "Linux Default Route & Gateway Unreachable SOP",
        "source_type": "SOP",
        "category": "NETWORK",
        "version": "1.0",
        "content": """SOP-LNX-004: Linux Default Gateway & Routing Recovery.
Symptoms:
1. Linux VM cannot route outside its broadcast domain; ping to default gateway fails.
2. ARP cache shows incomplete entries for gateway MAC address.
Resolution Procedure:
1. Flush stale neighbor cache: `ip neigh flush all`.
2. Run tool `renew_dhcp` to refresh routing table from DHCP gateway option.
3. Verify gateway reachability with `test_gateway`."""
    },
    {
        "doc_id": "KB-LNX-005",
        "title": "Linux UFW & iptables Firewall Port Blocking SOP",
        "source_type": "SOP",
        "category": "SECURITY",
        "version": "1.0",
        "content": """SOP-LNX-005: Linux UFW / iptables Port Blocking AISD Agent.
Symptoms:
1. Local agent daemon cannot connect to central server port 8000.
2. UFW default incoming/outgoing rule blocks port 8000.
Resolution Procedure:
1. Inspect firewall status: `ufw status verbose`.
2. Allow application communication: `ufw allow 8000/tcp` or iptables rule.
3. Test connectivity to central server."""
    }
]
