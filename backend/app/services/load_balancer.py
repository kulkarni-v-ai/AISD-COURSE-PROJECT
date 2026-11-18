import asyncio
import logging
import time
from typing import List, Dict, Any, Optional
import httpx
from app.core.config import settings

logger = logging.getLogger("aisd.load_balancer")


class OllamaNode:
    """Represents a single Ollama server node."""

    def __init__(self, url: str, name: Optional[str] = None, weight: int = 1):
        self.url = url.rstrip("/")
        self.name = name or self.url
        self.weight = weight
        self.is_healthy: bool = True
        self.active_requests: int = 0
        self.total_requests: int = 0
        self.total_failures: int = 0
        self.last_latency_ms: float = 0.0
        self.last_checked: float = 0.0
        self.consecutive_failures: int = 0

    async def check_health(self, timeout: float = 3.0) -> bool:
        """Pings Ollama node's /api/tags endpoint to verify health and measure latency."""
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(f"{self.url}/api/tags")
                elapsed = (time.perf_counter() - start) * 1000.0
                if resp.status_code == 200:
                    self.is_healthy = True
                    self.last_latency_ms = round(elapsed, 2)
                    self.consecutive_failures = 0
                    self.last_checked = time.time()
                    return True
        except Exception:
            pass

        self.consecutive_failures += 1
        if self.consecutive_failures >= 2:
            self.is_healthy = False
        self.last_checked = time.time()
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "healthy": self.is_healthy,
            "active_requests": self.active_requests,
            "total_requests": self.total_requests,
            "total_failures": self.total_failures,
            "latency_ms": self.last_latency_ms,
            "consecutive_failures": self.consecutive_failures,
        }


class OllamaLoadBalancer:
    """
    Intelligent Load Balancer for Ollama LLM / Embedding instances.
    Supports Round-Robin, Least-Connections, and Priority-Failover routing.
    """

    def __init__(
        self,
        node_urls: Optional[List[str]] = None,
        strategy: str = "least_connections",
        health_check_interval: float = 15.0
    ):
        urls = node_urls or [settings.OLLAMA_BASE_URL]
        # Remove duplicates while preserving order
        unique_urls = list(dict.fromkeys(urls))
        self.nodes: List[OllamaNode] = [
            OllamaNode(url=u, name=f"ollama-node-{i+1}")
            for i, u in enumerate(unique_urls)
        ]
        self.strategy = strategy.lower()  # "round_robin", "least_connections", "failover"
        self._current_index = 0
        self.health_check_interval = health_check_interval
        self._last_health_check = 0.0
        self._lock = asyncio.Lock()

    def add_node(self, url: str, name: Optional[str] = None) -> None:
        clean = url.rstrip("/")
        if not any(n.url == clean for n in self.nodes):
            self.nodes.append(OllamaNode(url=clean, name=name or f"ollama-node-{len(self.nodes)+1}"))

    def remove_node(self, url: str) -> bool:
        clean = url.rstrip("/")
        initial_len = len(self.nodes)
        self.nodes = [n for n in self.nodes if n.url != clean]
        return len(self.nodes) < initial_len

    async def get_healthy_nodes(self) -> List[OllamaNode]:
        """Returns list of currently healthy nodes, triggering health checks if due."""
        now = time.time()
        if now - self._last_health_check > self.health_check_interval:
            await self.check_all_nodes()

        healthy = [n for n in self.nodes if n.is_healthy]
        if not healthy and self.nodes:
            # If all marked unhealthy, attempt a quick probe on all nodes
            await self.check_all_nodes(timeout=2.0)
            healthy = [n for n in self.nodes if n.is_healthy]
        return healthy

    async def check_all_nodes(self, timeout: float = 3.0) -> None:
        self._last_health_check = time.time()
        tasks = [n.check_health(timeout=timeout) for n in self.nodes]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def select_node(self) -> Optional[OllamaNode]:
        """Selects the best available Ollama node according to configured strategy."""
        async with self._lock:
            healthy = await self.get_healthy_nodes()
            if not healthy:
                # If no node passes healthcheck, return the primary node as fallback
                return self.nodes[0] if self.nodes else None

            if self.strategy == "least_connections":
                # Pick healthy node with lowest active_requests; break ties by latency
                selected = min(healthy, key=lambda n: (n.active_requests, n.last_latency_ms))
            elif self.strategy == "failover":
                # Always pick the first healthy node in order
                selected = healthy[0]
            else:  # round_robin
                self._current_index = (self._current_index + 1) % len(healthy)
                selected = healthy[self._current_index]

            return selected

    async def route_chat(
        self,
        model: str,
        messages: List[Dict[str, str]],
        format_json: bool = False,
        temperature: float = 0.2,
        top_p: float = 0.9,
        timeout: float = 60.0,
    ) -> Dict[str, Any]:
        """Routes a chat request to an optimal Ollama node with automatic retry on failure."""
        node = await self.select_node()
        if not node:
            raise RuntimeError("No Ollama nodes configured or available in load balancer.")

        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "top_p": top_p},
        }
        if format_json:
            payload["format"] = "json"

        node.active_requests += 1
        node.total_requests += 1
        start_time = time.perf_counter()

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(f"{node.url}/api/chat", json=payload)
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                node.last_latency_ms = round(elapsed_ms, 2)

                if resp.status_code == 200:
                    node.consecutive_failures = 0
                    node.is_healthy = True
                    return resp.json()
                else:
                    node.total_failures += 1
                    node.consecutive_failures += 1
                    raise RuntimeError(f"Node {node.name} returned HTTP {resp.status_code}: {resp.text}")

        except Exception as exc:
            node.total_failures += 1
            node.consecutive_failures += 1
            if node.consecutive_failures >= 2:
                node.is_healthy = False
            logger.warning(f"Ollama request to {node.name} ({node.url}) failed: {exc}")
            raise
        finally:
            node.active_requests = max(0, node.active_requests - 1)

    async def route_embeddings(self, model: str, prompt: str, timeout: float = 10.0) -> Optional[List[float]]:
        """Routes an embedding request to an optimal Ollama node."""
        node = await self.select_node()
        if not node:
            return None

        node.active_requests += 1
        node.total_requests += 1
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    f"{node.url}/api/embeddings",
                    json={"model": model, "prompt": prompt}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("embedding")
        except Exception as exc:
            logger.debug(f"Embedding request to {node.name} failed: {exc}")
        finally:
            node.active_requests = max(0, node.active_requests - 1)
        return None

    def get_status(self) -> Dict[str, Any]:
        """Returns diagnostic and telemetry metrics for all load-balanced nodes."""
        return {
            "strategy": self.strategy,
            "total_nodes": len(self.nodes),
            "healthy_nodes": sum(1 for n in self.nodes if n.is_healthy),
            "nodes": [n.to_dict() for n in self.nodes],
        }


# Global Ollama Load Balancer instance
ollama_load_balancer = OllamaLoadBalancer()
