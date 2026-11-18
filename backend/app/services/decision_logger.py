import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.monitoring import AgentDecisionLog, EndpointTelemetrySnapshot


def compute_health_metrics(telemetry: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministically summarizes live telemetry into KPI metrics, health score (0-100), and anomalies."""
    telemetry = telemetry or {}
    adapter = telemetry.get("network_adapter", {}) or {}
    ip_cfg = telemetry.get("ip_config", {}) or {}
    gw = telemetry.get("gateway_ping", {}) or {}
    net = telemetry.get("internet_ping", {}) or {}
    dns = telemetry.get("dns_test", {}) or {}
    services = telemetry.get("services", {}) or {}

    adapter_status = str(adapter.get("status") or "Unknown")
    ipv4 = ip_cfg.get("ipv4_address")
    dhcp_enabled = ip_cfg.get("dhcp_enabled")
    static_dns = bool(ip_cfg.get("static_dns_configured")) or (ip_cfg.get("dns_dhcp_enabled") is False) or (dns.get("dns_dhcp_enabled") is False)
    dns_dhcp_enabled = False if static_dns else True

    gw_reachable = gw.get("reachable")
    gw_loss = int(gw.get("packet_loss_pct", 0 if gw_reachable else 100) or 0)
    gw_lat = gw.get("avg_latency_ms")

    net_reachable = net.get("reachable")
    net_loss = int(net.get("packet_loss_pct", 0 if net_reachable else 100) or 0)
    net_lat = net.get("avg_latency_ms")

    dns_resolved = dns.get("resolved")

    svc_keys = ["Spooler", "Dhcp", "Dnscache", "WlanSvc"]
    present_svcs = [k for k in svc_keys if k in services] or list(services.keys())
    total_svcs = len(present_svcs) if present_svcs else 4
    running_svcs = sum(
        1 for k in (present_svcs or svc_keys)
        if str(services.get(k, {}).get("status", "")).lower() == "running"
    )

    score = 100
    anomalies: List[str] = []

    if adapter_status.lower() in ("disabled", "not present"):
        score -= 50
        anomalies.append(f"Adapter '{adapter.get('name', 'Wi-Fi')}' is {adapter_status}")
    elif adapter_status.lower() == "disconnected" or adapter.get("media_state") == 2:
        score -= 45
        anomalies.append(f"Adapter '{adapter.get('name', 'Wi-Fi')}' is disconnected")

    if dhcp_enabled is False:
        score -= 20
        anomalies.append(f"Manual static IPv4 active ({ipv4 or 'unknown'}) with DHCP disabled")
    elif not ipv4 or str(ipv4).startswith("169.254."):
        score -= 30
        anomalies.append(f"Invalid or APIPA IPv4 address ({ipv4 or 'none'})")

    if static_dns:
        dns_list = ", ".join(ip_cfg.get("dns_servers") or dns.get("dns_servers") or []) or "manual"
        score -= 15
        anomalies.append(f"Manual static DNS configured ({dns_list})")

    if gw_reachable is False:
        score -= 25
        anomalies.append("Default gateway unreachable (100% packet loss)")
    elif gw_loss >= 20:
        score -= 12
        anomalies.append(f"High gateway packet loss ({gw_loss}%)")

    if net_reachable is False:
        score -= 15
        anomalies.append("Internet WAN (8.8.8.8) unreachable")
    elif net_loss >= 20:
        score -= 10
        anomalies.append(f"High WAN packet loss ({net_loss}%)")

    if dns_resolved is False:
        score -= 15
        anomalies.append("DNS domain lookup failed")

    if present_svcs and running_svcs < total_svcs:
        stopped = [k for k in present_svcs if str(services.get(k, {}).get("status", "")).lower() != "running"]
        score -= min(20, 7 * len(stopped))
        anomalies.append(f"Core service(s) not running: {', '.join(stopped)}")

    score = max(0, min(100, int(score)))

    return {
        "ip_address": ipv4,
        "adapter_name": ip_cfg.get("adapter_name") or adapter.get("name"),
        "adapter_status": adapter_status,
        "dhcp_enabled": dhcp_enabled,
        "dns_dhcp_enabled": dns_dhcp_enabled,
        "static_dns_configured": static_dns,
        "gateway_ip": ip_cfg.get("default_gateway") or gw.get("target_gateway"),
        "gateway_reachable": gw_reachable,
        "gateway_latency_ms": float(gw_lat) if gw_lat is not None else None,
        "gateway_loss_pct": gw_loss,
        "internet_reachable": net_reachable,
        "internet_latency_ms": float(net_lat) if net_lat is not None else None,
        "internet_loss_pct": net_loss,
        "dns_resolved": dns_resolved,
        "services_running_count": running_svcs,
        "services_total_count": total_svcs,
        "health_score": score,
        "anomaly_count": len(anomalies),
        "anomalies": anomalies,
    }


def record_telemetry_snapshot(
    db: AsyncSession,
    *,
    endpoint_id: int,
    agent_uuid: str,
    hostname: str,
    telemetry: Dict[str, Any],
    source_mode: str = "AGENT_ONLINE",
    fallback_ip: Optional[str] = None,
) -> Tuple[EndpointTelemetrySnapshot, Dict[str, Any]]:
    metrics = compute_health_metrics(telemetry)
    snap = EndpointTelemetrySnapshot(
        endpoint_id=endpoint_id,
        agent_uuid=agent_uuid,
        hostname=hostname,
        ip_address=metrics["ip_address"] or fallback_ip,
        adapter_name=metrics["adapter_name"],
        adapter_status=metrics["adapter_status"],
        dhcp_enabled=(1 if metrics["dhcp_enabled"] is True else (0 if metrics["dhcp_enabled"] is False else None)),
        dns_dhcp_enabled=(1 if metrics["dns_dhcp_enabled"] else 0),
        static_dns_configured=(1 if metrics["static_dns_configured"] else 0),
        gateway_ip=metrics["gateway_ip"],
        gateway_reachable=(1 if metrics["gateway_reachable"] is True else (0 if metrics["gateway_reachable"] is False else None)),
        gateway_latency_ms=metrics["gateway_latency_ms"],
        gateway_loss_pct=metrics["gateway_loss_pct"],
        internet_reachable=(1 if metrics["internet_reachable"] is True else (0 if metrics["internet_reachable"] is False else None)),
        internet_latency_ms=metrics["internet_latency_ms"],
        internet_loss_pct=metrics["internet_loss_pct"],
        dns_resolved=(1 if metrics["dns_resolved"] is True else (0 if metrics["dns_resolved"] is False else None)),
        services_running_count=metrics["services_running_count"],
        services_total_count=metrics["services_total_count"],
        health_score=metrics["health_score"],
        anomaly_count=metrics["anomaly_count"],
        source_mode=source_mode,
        telemetry_json=telemetry,
        recorded_at=datetime.now(timezone.utc),
    )
    db.add(snap)
    return snap, metrics


def record_decision_log(
    db: AsyncSession,
    *,
    why_explanation: str,
    actor_source: str = "RULE_ENGINE",
    decision_type: str = "RULE_DIAGNOSIS",
    rule_or_model: Optional[str] = None,
    action_taken: Optional[str] = None,
    observed_state: Optional[str] = None,
    expected_state: Optional[str] = None,
    confidence: Optional[float] = None,
    outcome: str = "INFO",
    endpoint_id: Optional[int] = None,
    agent_uuid: Optional[str] = None,
    hostname: Optional[str] = None,
    incident_id: Optional[int] = None,
    evidence_json: Optional[Dict[str, Any]] = None,
    log_uuid: Optional[str] = None,
) -> AgentDecisionLog:
    entry = AgentDecisionLog(
        log_uuid=log_uuid or f"dec-{uuid.uuid4().hex[:16]}",
        endpoint_id=endpoint_id,
        agent_uuid=agent_uuid,
        hostname=hostname,
        incident_id=incident_id,
        actor_source=actor_source,
        decision_type=decision_type,
        rule_or_model=rule_or_model,
        action_taken=action_taken,
        why_explanation=why_explanation,
        observed_state=(observed_state[:250] if observed_state else None),
        expected_state=(expected_state[:250] if expected_state else None),
        confidence=confidence,
        outcome=outcome,
        evidence_json=evidence_json or {},
        created_at=datetime.now(timezone.utc),
    )
    db.add(entry)
    return entry
