#!/usr/bin/env python3
"""
AISD Independent Ollama Load Balancer & Reverse Proxy
Listens on a designated port (e.g. 11435 or 8080) and distributes requests across
multiple Ollama instances with active health checks, failover, and metrics.
"""

import sys
import os
import time
import asyncio
from typing import List, Dict, Any, Optional
import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
import uvicorn

DEFAULT_UPSTREAMS = [
    "http://127.0.0.1:11434",
]

UPSTREAM_NODES = os.getenv("OLLAMA_UPSTREAM_NODES", ",".join(DEFAULT_UPSTREAMS)).split(",")
STRATEGY = os.getenv("OLLAMA_LB_STRATEGY", "least_connections").lower()
PORT = int(os.getenv("OLLAMA_LB_PORT", "11435"))
HOST = os.getenv("OLLAMA_LB_HOST", "0.0.0.0")

app = FastAPI(title="AISD Ollama Load Balancer", version="1.0.0")


class NodeState:
    def __init__(self, url: str):
        self.url = url.strip().rstrip("/")
        self.healthy = True
        self.active_requests = 0
        self.total_requests = 0
        self.failures = 0
        self.latency_ms = 0.0

    async def probe(self) -> bool:
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.get(f"{self.url}/api/tags")
                self.latency_ms = round((time.perf_counter() - start) * 1000, 2)
                self.healthy = (res.status_code == 200)
                return self.healthy
        except Exception:
            self.healthy = False
            return False


nodes = [NodeState(u) for u in UPSTREAM_NODES if u.strip()]
rr_index = 0
lock = asyncio.Lock()


async def pick_node() -> Optional[NodeState]:
    global rr_index
    async with lock:
        healthy = [n for n in nodes if n.healthy]
        if not healthy:
            return nodes[0] if nodes else None
        if STRATEGY == "least_connections":
            return min(healthy, key=lambda n: (n.active_requests, n.latency_ms))
        else:
            rr_index = (rr_index + 1) % len(healthy)
            return healthy[rr_index]


@app.get("/health")
@app.get("/lb/status")
async def lb_status():
    return {
        "status": "healthy",
        "strategy": STRATEGY,
        "total_nodes": len(nodes),
        "healthy_nodes": sum(1 for n in nodes if n.healthy),
        "nodes": [
            {
                "url": n.url,
                "healthy": n.healthy,
                "active_requests": n.active_requests,
                "total_requests": n.total_requests,
                "failures": n.failures,
                "latency_ms": n.latency_ms
            }
            for n in nodes
        ]
    }


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS"])
async def proxy_request(path: str, request: Request):
    node = await pick_node()
    if not node:
        return JSONResponse(status_code=503, content={"error": "No Ollama upstreams available."})

    target_url = f"{node.url}/{path}"
    body = await request.body()
    headers = dict(request.headers)
    headers.pop("host", None)

    node.active_requests += 1
    node.total_requests += 1
    start = time.perf_counter()

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                params=dict(request.query_params),
                content=body
            )
            node.latency_ms = round((time.perf_counter() - start) * 1000, 2)
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers=dict(resp.headers),
                media_type=resp.headers.get("content-type")
            )
    except Exception as exc:
        node.failures += 1
        node.healthy = False
        return JSONResponse(status_code=502, content={"error": f"Upstream error from {node.url}: {exc}"})
    finally:
        node.active_requests = max(0, node.active_requests - 1)


@app.on_event("startup")
async def startup_check():
    for n in nodes:
        await n.probe()


if __name__ == "__main__":
    print(f"Starting AISD Ollama Load Balancer on {HOST}:{PORT} (Strategy: {STRATEGY})...")
    print(f"Upstream Nodes: {[n.url for n in nodes]}")
    uvicorn.run(app, host=HOST, port=PORT)
