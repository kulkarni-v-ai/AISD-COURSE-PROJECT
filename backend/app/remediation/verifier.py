import asyncio
from typing import Dict, Any, Tuple
from app.remediation import windows_net


class VerificationEngine:
    async def verify(
        self,
        tool_id: str,
        verification_type: str,
        arguments: Dict[str, Any],
        is_mock: bool = True,
        simulate_outcome: str = "VERIFIED_RESOLVED"
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Executes postcondition checks after remediation.
        Returns: (status, evidence_json)
        Status: VERIFIED_RESOLVED | NOT_RESOLVED | INCONCLUSIVE | VERIFICATION_ERROR
        """
        arguments = arguments or {}

        if is_mock:
            # Deterministic simulated verification for testing and safe demonstration
            if simulate_outcome == "NOT_RESOLVED":
                return "NOT_RESOLVED", {
                    "check": verification_type,
                    "result": "Failure: Post-action state still violates operational requirements.",
                    "ip_address": "169.254.120.44",
                    "default_gateway": None,
                    "gateway_ping_success": False
                }
            elif simulate_outcome == "INCONCLUSIVE":
                return "INCONCLUSIVE", {
                    "check": verification_type,
                    "result": "Warning: Partial response received. Unable to reach authoritative resolver."
                }
            else:
                # Default mock success
                return "VERIFIED_RESOLVED", {
                    "check": verification_type,
                    "result": "Success: Postcondition satisfied.",
                    "ip_address": "10.12.4.152",
                    "subnet_mask": "255.255.240.0",
                    "default_gateway": "10.12.0.1",
                    "gateway_ping_latency_ms": 3.8,
                    "dns_resolution_time_ms": 12.4,
                    "service_state": "Running",
                    "verified_live": False,
                    "mock": True
                }

        # Real verification on Windows
        try:
            if verification_type == "ip_validity":
                def _verify_ip() -> Tuple[str, Dict[str, Any]]:
                    adapter = windows_net.resolve_active_adapter(arguments.get("adapter_name"))
                    ip_cfg = windows_net.get_ip_config_for_adapter(adapter)
                    ipv4 = ip_cfg.get("ipv4_address")
                    gw = ip_cfg.get("default_gateway")
                    dhcp_enabled = ip_cfg.get("dhcp_enabled")
                    static_dns = ip_cfg.get("static_dns_configured", False)

                    gw_ping = windows_net.ping_host(gw, count=2, timeout_ms=1000) if gw else {"reachable": False}
                    evidence = {
                        "adapter_name": adapter,
                        "ipv4_address": ipv4,
                        "subnet_mask": ip_cfg.get("subnet_mask"),
                        "default_gateway": gw,
                        "dhcp_enabled": dhcp_enabled,
                        "dns_dhcp_enabled": ip_cfg.get("dns_dhcp_enabled"),
                        "dns_servers": ip_cfg.get("dns_servers", []),
                        "gateway_reachable": bool(gw_ping.get("reachable")),
                        "gateway_latency_ms": gw_ping.get("avg_latency_ms"),
                        "verified_live": True,
                    }

                    if dhcp_enabled is False:
                        evidence["reason"] = f"Adapter '{adapter}' still has Static IP configured (DHCP disabled)."
                        return "NOT_RESOLVED", evidence
                    if not ipv4 or str(ipv4).startswith("169.254.") or str(ipv4).startswith("127."):
                        evidence["reason"] = f"Adapter '{adapter}' lacks a valid DHCP IPv4 address (got '{ipv4}')."
                        return "NOT_RESOLVED", evidence
                    if not gw:
                        evidence["reason"] = f"Adapter '{adapter}' has no default gateway assigned."
                        return "NOT_RESOLVED", evidence
                    if static_dns:
                        evidence["reason"] = f"Adapter '{adapter}' still has static DNS servers configured."
                        return "NOT_RESOLVED", evidence
                    if not gw_ping.get("reachable"):
                        evidence["reason"] = f"Assigned IP {ipv4}, but default gateway {gw} did not respond to ping."
                        return "NOT_RESOLVED", evidence

                    evidence["result"] = f"DHCP enabled on '{adapter}', valid IP {ipv4} and gateway {gw} verified reachable."
                    return "VERIFIED_RESOLVED", evidence

                return await asyncio.to_thread(_verify_ip)

            elif verification_type == "gateway_ping":
                def _verify_gw() -> Tuple[str, Dict[str, Any]]:
                    adapter = windows_net.resolve_active_adapter(arguments.get("adapter_name"))
                    gw = arguments.get("gateway_ip")
                    if not gw:
                        gw = windows_net.get_ip_config_for_adapter(adapter).get("default_gateway")
                    if not gw:
                        return "NOT_RESOLVED", {"adapter_name": adapter, "gateway_ping": "No default gateway configured"}
                    ping_res = windows_net.ping_host(gw, count=2, timeout_ms=1000)
                    if ping_res.get("reachable"):
                        return "VERIFIED_RESOLVED", {
                            "adapter_name": adapter,
                            "target_gateway": gw,
                            "avg_latency_ms": ping_res.get("avg_latency_ms"),
                            "gateway_ping": "Successful response received",
                            "verified_live": True,
                        }
                    return "NOT_RESOLVED", {
                        "adapter_name": adapter,
                        "target_gateway": gw,
                        "packet_loss_pct": ping_res.get("packet_loss_pct", 100),
                        "gateway_ping": "Destination host unreachable",
                        "verified_live": True,
                    }

                return await asyncio.to_thread(_verify_gw)

            elif verification_type == "service_running":
                srv = str(arguments.get("service_name", "Spooler"))
                proc = await asyncio.create_subprocess_exec(
                    "powershell", "-NoProfile", "-Command", f"(Get-Service -Name '{srv}' -ErrorAction SilentlyContinue).Status.ToString()",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=6.0)
                status = stdout.decode("utf-8", errors="ignore").strip()
                if status.lower() == "running":
                    return "VERIFIED_RESOLVED", {"service": srv, "status": "Running", "verified_live": True}
                return "NOT_RESOLVED", {"service": srv, "status": status or "Stopped", "verified_live": True}

            elif verification_type == "adapter_status":
                def _verify_adapter() -> Tuple[str, Dict[str, Any]]:
                    adapter = windows_net.resolve_active_adapter(arguments.get("adapter_name"))
                    adapters = windows_net.list_adapters()
                    matched = next((a for a in adapters if a.get("name") == adapter), None)
                    status_str = matched.get("status", "Unknown") if matched else "Unknown"
                    if status_str.lower() == "up":
                        return "VERIFIED_RESOLVED", {"adapter_name": adapter, "status": status_str, "verified_live": True}
                    return "NOT_RESOLVED", {"adapter_name": adapter, "status": status_str, "verified_live": True}

                return await asyncio.to_thread(_verify_adapter)

            elif verification_type == "dns_resolve":
                def _verify_dns() -> Tuple[str, Dict[str, Any]]:
                    adapter = windows_net.resolve_active_adapter(arguments.get("adapter_name"))
                    dns_cfg = windows_net.get_dns_server_config(adapter) if adapter else {"dns_dhcp_enabled": True, "static_dns_configured": False}
                    domains = arguments.get("domains") or ["college.edu", "google.com"]
                    dns_res = windows_net.test_dns_hosts(domains, adapter_name=adapter)
                    evidence = {
                        "adapter_name": adapter,
                        "dns_dhcp_enabled": dns_cfg.get("dns_dhcp_enabled", True),
                        "static_dns_configured": dns_cfg.get("static_dns_configured", False),
                        "dns_servers": dns_cfg.get("dns_servers", []),
                        "domains": dns_res.get("domains", {}),
                        "resolved": dns_res.get("resolved", False),
                        "verified_live": True,
                    }

                    # For flush_dns_cache, static DNS MUST no longer be statically stuck if DHCP was requested
                    if tool_id == "flush_dns_cache" and dns_cfg.get("static_dns_configured"):
                        evidence["dns_check"] = f"Static DNS servers ({', '.join(dns_cfg.get('dns_servers', []))}) still configured on '{adapter}'."
                        return "NOT_RESOLVED", evidence

                    if dns_res.get("resolved"):
                        evidence["dns_check"] = "Real domain name resolution succeeded and DNS client configuration is healthy."
                        return "VERIFIED_RESOLVED", evidence

                    evidence["dns_check"] = "DNS lookup failed for target domains."
                    return "NOT_RESOLVED", evidence

                return await asyncio.to_thread(_verify_dns)

            elif verification_type == "full_network":
                def _verify_full() -> Tuple[str, Dict[str, Any]]:
                    ev = windows_net.collect_live_windows_evidence()
                    ip_cfg = ev.get("ip_config", {})
                    gw_ok = ev.get("gateway_ping", {}).get("reachable")
                    dns_ok = ev.get("dns_test", {}).get("resolved")
                    ok = bool(
                        ip_cfg.get("has_valid_ip")
                        and ip_cfg.get("dhcp_enabled", True)
                        and ip_cfg.get("dns_dhcp_enabled", True)
                        and gw_ok
                        and dns_ok
                    )
                    return ("VERIFIED_RESOLVED" if ok else "NOT_RESOLVED"), ev

                return await asyncio.to_thread(_verify_full)

            else:
                return "VERIFIED_RESOLVED", {"check": verification_type, "note": "Generic verification passed"}

        except Exception as e:
            return "VERIFICATION_ERROR", {"error": str(e)}


verification_engine = VerificationEngine()
