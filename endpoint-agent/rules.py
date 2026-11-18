from typing import Dict, Any, List, Optional


class LocalRuleEngine:
    def evaluate(self, evidence: Dict[str, Any]) -> Dict[str, Any]:
        """Runs offline deterministic checks on collected telemetry across all Windows failure conditions + static IP/DNS."""
        ip_conf = evidence.get("ip_config", {})
        ipv4 = str(ip_conf.get("ipv4_address", "") or "").strip()
        gateway = ip_conf.get("default_gateway")
        gw_ping = evidence.get("gateway_ping", {})
        net_ping = evidence.get("internet_ping", {})
        dns_test = evidence.get("dns_test", {})
        adapter = evidence.get("network_adapter", {})
        adapters_list = evidence.get("adapters_list", [])
        firewall = evidence.get("firewall", {})
        services = evidence.get("services", {})

        hypotheses = []
        recommended_tools = []
        sources = []

        adapter_status = str(adapter.get("status", "")).lower()
        adapter_name = ip_conf.get("adapter_name") or adapter.get("name", "Wi-Fi")

        # 1. No Network Adapter Available (Disabled / Not Present / Driver Failure)
        physical_adapters = [a for a in adapters_list if not a.get("is_virtual", False)]
        all_disabled = bool(physical_adapters and all(a.get("status", "").lower() in ["disabled", "not present"] for a in physical_adapters))
        if adapter_status in ["disabled", "not present"] or all_disabled:
            hypotheses.append({
                "cause": "No active network adapter available (adapter disabled or driver failure)",
                "confidence": 0.98,
                "evidence_ids": ["network_adapter", "adapters_list"],
                "missing_evidence": ["driver_state"],
                "next_checks": ["enable_adapter", "reinstall_driver"]
            })
            recommended_tools.append("enable_adapter")
            sources.append("KB-NET-004")

        # 2. Network Cable or Wi-Fi Connection Lost (Disconnected / Media Unplugged)
        elif adapter_status in ["disconnected"] or adapter.get("media_state") == 2:
            hypotheses.append({
                "cause": "Network cable unplugged or Wi-Fi connection lost",
                "confidence": 0.95,
                "evidence_ids": ["network_adapter"],
                "missing_evidence": ["ap_beacon_visibility"],
                "next_checks": ["reconnect_wifi", "check_cable"]
            })
            recommended_tools.append("collect_network_status")
            sources.append("KB-NET-006")
        else:
            # 3. Static IP Configuration Detected (DHCP Disabled)
            if ip_conf.get("dhcp_enabled") is False:
                hypotheses.append({
                    "cause": f"Manual static IPv4 configuration detected on '{adapter_name}' (DHCP disabled)",
                    "confidence": 0.92,
                    "evidence_ids": ["ip_config", "network_adapter"],
                    "missing_evidence": ["dhcp_server_lease_offer"],
                    "next_checks": ["renew_dhcp", "test_gateway"]
                })
                recommended_tools.append("renew_dhcp")
                sources.append("KB-NET-001")

            # 4. No IP Address Assigned (APIPA 169.254.x.x, 0.0.0.0, missing IP, or DHCP failure)
            if (
                ipv4.startswith("169.254.")
                or ipv4 == "0.0.0.0"
                or ("ipv4_address" in ip_conf and not ipv4 and not ip_conf.get("has_valid_ip") and ip_conf.get("dhcp_enabled", True))
                or (ipv4 and not gateway and ip_conf.get("dhcp_enabled", True))
            ):
                hypotheses.append({
                    "cause": "DHCP lease acquisition failure (APIPA 169.254.x.x or missing IPv4 lease)",
                    "confidence": 0.95,
                    "evidence_ids": ["ip_config"],
                    "missing_evidence": ["dhcp_server_ack"],
                    "next_checks": ["renew_dhcp"]
                })
                recommended_tools.append("renew_dhcp")
                sources.append("KB-NET-001")

            # 5. Default Gateway Unreachable
            elif gateway and (gw_ping.get("reachable") is False or gw_ping.get("packet_loss_pct", 0) == 100):
                hypotheses.append({
                    "cause": "Default gateway unreachable (100% packet loss)",
                    "confidence": 0.90,
                    "evidence_ids": ["gateway_ping", "ip_config"],
                    "missing_evidence": ["arp_cache"],
                    "next_checks": ["renew_dhcp", "test_gateway"]
                })
                recommended_tools.append("renew_dhcp")
                recommended_tools.append("test_gateway")
                sources.append("KB-NET-002")

            # 6. Internet Connection Lost (Gateway reachable, but external WAN / 8.8.8.8 has 100% loss)
            elif gw_ping.get("reachable") is True and (net_ping.get("reachable") is False or net_ping.get("packet_loss_pct", 0) == 100):
                hypotheses.append({
                    "cause": "Local network functional, but Internet WAN connection lost (ISP or router WAN outage)",
                    "confidence": 0.92,
                    "evidence_ids": ["internet_ping", "gateway_ping"],
                    "missing_evidence": ["isp_gateway_status"],
                    "next_checks": ["test_gateway"]
                })
                recommended_tools.append("test_gateway")
                sources.append("KB-NET-007")

            # 7. High Latency or Severe Packet Loss (20% <= loss < 100% or > 5000ms latency)
            elif ((20 <= gw_ping.get("packet_loss_pct", 0) < 100) or (20 <= net_ping.get("packet_loss_pct", 0) < 100) or
                  (gw_ping.get("avg_latency_ms") and gw_ping["avg_latency_ms"] > 5000) or
                  (net_ping.get("avg_latency_ms") and net_ping["avg_latency_ms"] > 5000)):
                loss = max(gw_ping.get("packet_loss_pct", 0), net_ping.get("packet_loss_pct", 0))
                lat = max(gw_ping.get("avg_latency_ms") or 0, net_ping.get("avg_latency_ms") or 0)
                hypotheses.append({
                    "cause": f"Severe network degradation detected ({loss}% packet loss, {lat}ms latency)",
                    "confidence": 0.85,
                    "evidence_ids": ["gateway_ping", "internet_ping"],
                    "missing_evidence": ["wi_fi_rssi_dbm"],
                    "next_checks": ["renew_dhcp", "test_gateway"]
                })
                recommended_tools.append("renew_dhcp")
                sources.append("KB-NET-010")
                sources.append("KB-NET-007")

            # 8. DNS Failure (Internet/Gateway reachable, but domain lookup fails)
            if dns_test and dns_test.get("resolved") is False:
                hypotheses.append({
                    "cause": "DNS resolver failure or stale cache",
                    "confidence": 0.88,
                    "evidence_ids": ["dns_test"],
                    "missing_evidence": ["dns_server_ip"],
                    "next_checks": ["flush_dns_cache"]
                })
                recommended_tools.append("flush_dns_cache")
                sources.append("KB-NET-003")

            # 9. Manual Static DNS Servers Configured
            if (ip_conf.get("dns_dhcp_enabled") is False) or (dns_test.get("dns_dhcp_enabled") is False):
                dns_servers = ip_conf.get("dns_servers") or dns_test.get("dns_servers") or []
                dns_str = ", ".join(dns_servers) if dns_servers else "manual custom servers"
                hypotheses.append({
                    "cause": f"Manual static DNS servers configured on '{adapter_name}' ({dns_str})",
                    "confidence": 0.90,
                    "evidence_ids": ["ip_config", "dns_test"],
                    "missing_evidence": ["dhcp_dns_servers"],
                    "next_checks": ["flush_dns_cache"]
                })
                recommended_tools.append("flush_dns_cache")
                sources.append("KB-NET-003")

            # 10. Firewall Blocking Communication
            if firewall and any(v is False for v in firewall.values()):
                hypotheses.append({
                    "cause": "Windows Defender Firewall configuration mismatch or rule blocking",
                    "confidence": 0.75,
                    "evidence_ids": ["firewall"],
                    "missing_evidence": ["firewall_port_rules"],
                    "next_checks": ["check_firewall_rules"]
                })
                sources.append("KB-NET-008")

        # Multiple Conflicting Network Interfaces Active
        active_physical = [a for a in physical_adapters if a.get("status", "").lower() == "up"]
        if len(active_physical) > 1:
            hypotheses.append({
                "cause": f"Multiple active physical network interfaces detected ({', '.join([a['name'] for a in active_physical])})",
                "confidence": 0.70,
                "evidence_ids": ["adapters_list"],
                "missing_evidence": ["routing_metric_table"],
                "next_checks": ["renew_dhcp", "flush_dns_cache"]
            })
            recommended_tools.append("flush_dns_cache")
            sources.append("KB-NET-009")

        # Print Spooler & Core Network Windows Services Stopped
        if services.get("Spooler", {}).get("status", "").lower() in ["stopped", "paused", "error"]:
            hypotheses.append({
                "cause": "Print Spooler service stopped",
                "confidence": 0.96,
                "evidence_ids": ["services"],
                "missing_evidence": ["printer_driver_error"],
                "next_checks": ["restart_approved_service"]
            })
            recommended_tools.append("restart_approved_service")
            sources.append("KB-PRT-001")

        if services.get("Dhcp", {}).get("status", "").lower() in ["stopped", "paused", "error"]:
            hypotheses.append({
                "cause": "DHCP Client Windows service ('Dhcp') stopped",
                "confidence": 0.96,
                "evidence_ids": ["services"],
                "missing_evidence": ["service_start_type"],
                "next_checks": ["restart_approved_service"]
            })
            recommended_tools.append("restart_approved_service")
            sources.append("KB-NET-001")

        if services.get("Dnscache", {}).get("status", "").lower() in ["stopped", "paused", "error"]:
            hypotheses.append({
                "cause": "DNS Client Windows service ('Dnscache') stopped",
                "confidence": 0.96,
                "evidence_ids": ["services"],
                "missing_evidence": ["service_start_type"],
                "next_checks": ["restart_approved_service"]
            })
            recommended_tools.append("restart_approved_service")
            sources.append("KB-NET-003")

        if not hypotheses:
            return {
                "status": "insufficient_evidence",
                "summary": "Local deterministic rules found no anomalies. Issue may require central AI or manual technician review.",
                "hypotheses": [],
                "recommended_tool_ids": ["collect_network_status"],
                "requires_technician": True,
                "sources": []
            }

        dedup_tools = list(dict.fromkeys(recommended_tools))
        dedup_sources = list(dict.fromkeys(sources))
        summary = "; ".join([h["cause"] for h in hypotheses])
        return {
            "status": "hypotheses",
            "summary": f"Local rule diagnosis: {summary}",
            "hypotheses": hypotheses,
            "recommended_tool_ids": dedup_tools,
            "requires_technician": any(h.get("confidence", 0) < 0.7 for h in hypotheses),
            "sources": dedup_sources
        }


local_rule_engine = LocalRuleEngine()
