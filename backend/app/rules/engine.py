from typing import Dict, Any, List, Optional
from app.schemas.diagnostic import DiagnosisResult, HypothesisItem


class DiagnosticRule:
    rule_id: str
    name: str
    description: str

    def evaluate(self, evidence: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        raise NotImplementedError


class ApipaDhcpFailureRule(DiagnosticRule):
    rule_id: str = "RULE-NET-001"
    name: str = "APIPA Address Detected (DHCP Lease Failure)"
    description: str = "Detects 169.254.x.x link-local auto-configuration indicating DHCP failure."

    def evaluate(self, evidence: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        ip_conf = evidence.get("ip_config", {})
        ipv4 = str(ip_conf.get("ipv4_address", "")).strip()
        gateway = str(ip_conf.get("default_gateway", "")).strip()

        if ipv4.startswith("169.254.") or (ipv4 and not gateway and ip_conf.get("dhcp_enabled", True)):
            return {
                "cause": "DHCP lease acquisition failure (APIPA 169.254.x.x assigned)",
                "confidence": 0.95,
                "evidence_ids": ["ip_config"],
                "missing_evidence": ["dhcp_server_reachability"],
                "next_checks": ["renew_dhcp", "test_gateway"],
                "recommended_tool_ids": ["renew_dhcp"],
                "requires_technician": False,
                "sources": ["KB-NET-001"],
                "summary": f"Network adapter has self-assigned an APIPA IP address ({ipv4}) with no default gateway. The device failed to acquire a DHCP lease."
            }
        return None


class GatewayUnreachableRule(DiagnosticRule):
    rule_id: str = "RULE-NET-002"
    name: str = "Default Gateway Unreachable"
    description: str = "Default gateway is configured but ICMP ping / reachability test fails."

    def evaluate(self, evidence: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        gw_test = evidence.get("gateway_ping", {})
        ip_conf = evidence.get("ip_config", {})
        gateway = ip_conf.get("default_gateway")

        if gateway and (gw_test.get("reachable") is False or gw_test.get("packet_loss_pct", 0) == 100):
            return {
                "cause": "Default gateway unreachable or local subnet disconnection",
                "confidence": 0.90,
                "evidence_ids": ["gateway_ping", "ip_config"],
                "missing_evidence": ["arp_cache", "router_interface_status"],
                "next_checks": ["test_gateway", "renew_dhcp"],
                "recommended_tool_ids": ["test_gateway", "renew_dhcp"],
                "requires_technician": False,
                "sources": ["KB-NET-002"],
                "summary": f"Default gateway {gateway} is unreachable (100% packet loss). Local router or Wi-Fi AP connection may be degraded."
            }
        return None


class DnsResolutionFailureRule(DiagnosticRule):
    rule_id: str = "RULE-NET-003"
    name: str = "DNS Resolution Failure"
    description: str = "Gateway is reachable, but DNS queries fail."

    def evaluate(self, evidence: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        dns_test = evidence.get("dns_test", {})
        gw_test = evidence.get("gateway_ping", {})

        # If gateway is reachable or skipped, but DNS resolution completely failed
        if dns_test and dns_test.get("resolved") is False:
            gw_ok = gw_test.get("reachable", True)
            confidence = 0.88 if gw_ok else 0.70
            return {
                "cause": "DNS server unreachable or misconfigured",
                "confidence": confidence,
                "evidence_ids": ["dns_test"],
                "missing_evidence": ["dns_cache", "dns_server_ping"],
                "next_checks": ["flush_dns_cache", "test_dns"],
                "recommended_tool_ids": ["flush_dns_cache"],
                "requires_technician": False,
                "sources": ["KB-NET-003"],
                "summary": "DNS lookup failed while network layer is partially or fully connected. DNS cache corruption or unresponsive campus DNS resolver."
            }
        return None


class AdapterDisconnectedRule(DiagnosticRule):
    rule_id: str = "RULE-NET-004"
    name: str = "Network Adapter Down / Disabled"
    description: str = "Primary network adapter is administratively disabled or disconnected."

    def evaluate(self, evidence: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        adapter = evidence.get("network_adapter", {})
        status = adapter.get("status", "").lower()
        if status in ["down", "disconnected", "disabled", "not present"]:
            return {
                "cause": "Physical or Wi-Fi network adapter is disconnected or disabled",
                "confidence": 0.98,
                "evidence_ids": ["network_adapter"],
                "missing_evidence": ["wi_fi_switch_state"],
                "next_checks": ["enable_adapter"],
                "recommended_tool_ids": ["enable_adapter"],
                "requires_technician": False,
                "sources": ["KB-NET-004"],
                "summary": f"Network adapter '{adapter.get('name', 'Wi-Fi')}' is currently {status}."
            }
        return None


class PrintSpoolerStoppedRule(DiagnosticRule):
    rule_id: str = "RULE-PRT-001"
    name: str = "Print Spooler Service Stopped"
    description: str = "Windows Print Spooler service (Spooler) is in stopped or error state."

    def evaluate(self, evidence: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        services = evidence.get("services", {})
        spooler = services.get("Spooler", {})
        if spooler.get("status", "").lower() in ["stopped", "paused", "error"]:
            return {
                "cause": "Windows Print Spooler service is stopped",
                "confidence": 0.96,
                "evidence_ids": ["services"],
                "missing_evidence": ["printer_queue_stuck_jobs"],
                "next_checks": ["restart_approved_service"],
                "recommended_tool_ids": ["restart_approved_service"],
                "requires_technician": False,
                "sources": ["KB-PRT-001"],
                "summary": "The Print Spooler service (Spooler) is stopped. Documents cannot be sent to printers."
            }
        return None


class CaptivePortalRule(DiagnosticRule):
    rule_id: str = "RULE-NET-005"
    name: str = "Captive Portal Login Required"
    description: str = "Gateway reachable, HTTP probe redirected to college login portal."

    def evaluate(self, evidence: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        http_test = evidence.get("http_probe", {})
        if http_test.get("is_captive_portal") is True or http_test.get("status_code") in [302, 307] and "login" in str(http_test.get("redirect_url", "")).lower():
            return {
                "cause": "Campus Wi-Fi captive portal authentication required",
                "confidence": 0.92,
                "evidence_ids": ["http_probe"],
                "missing_evidence": ["student_credentials_validity"],
                "next_checks": ["open_portal_url"],
                "recommended_tool_ids": ["collect_network_status"],
                "requires_technician": False,
                "sources": ["KB-NET-005"],
                "summary": "Campus Wi-Fi requires captive portal sign-in. HTTP requests are being redirected to the authentication gateway."
            }
        return None


class MediaDisconnectedRule(DiagnosticRule):
    rule_id: str = "RULE-NET-006"
    name: str = "Network Cable Unplugged / Wi-Fi Disconnected"
    description: str = "Adapter exists but media state is disconnected or cable is unplugged."

    def evaluate(self, evidence: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        adapter = evidence.get("network_adapter", {})
        status = str(adapter.get("status", "")).lower()
        media_state = adapter.get("media_state")
        if status in ["disconnected"] or media_state == 2:
            return {
                "cause": "Network cable unplugged or Wi-Fi connection lost",
                "confidence": 0.95,
                "evidence_ids": ["network_adapter"],
                "missing_evidence": ["ap_beacon_visibility"],
                "next_checks": ["reconnect_wifi", "check_cable"],
                "recommended_tool_ids": ["collect_network_status"],
                "requires_technician": False,
                "sources": ["KB-NET-006"],
                "summary": f"Network adapter '{adapter.get('name', 'Ethernet')}' reports media disconnected. Cable may be unplugged or Wi-Fi out of range."
            }
        return None


class InternetWanLostRule(DiagnosticRule):
    rule_id: str = "RULE-NET-007"
    name: str = "Internet WAN Lost (LAN Functional)"
    description: str = "Default gateway is reachable via ICMP, but external Internet IP (8.8.8.8) fails."

    def evaluate(self, evidence: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        gw_test = evidence.get("gateway_ping", {})
        net_test = evidence.get("internet_ping", {})
        if gw_test.get("reachable") is True and net_test.get("reachable") is False and net_test.get("packet_loss_pct", 0) == 100:
            return {
                "cause": "Local network functional, but Internet WAN connection lost (ISP or router WAN outage)",
                "confidence": 0.92,
                "evidence_ids": ["internet_ping", "gateway_ping"],
                "missing_evidence": ["isp_gateway_status"],
                "next_checks": ["test_gateway"],
                "recommended_tool_ids": ["test_gateway"],
                "requires_technician": True,
                "sources": ["KB-NET-007"],
                "summary": "Local network gateway responds, but external Internet connectivity is completely down. Likely an ISP upstream link outage."
            }
        return None


class FirewallBlockedRule(DiagnosticRule):
    rule_id: str = "RULE-NET-008"
    name: str = "Windows Defender Firewall Blocking Communication"
    description: str = "Firewall profiles active with blocked ports or profile mismatch."

    def evaluate(self, evidence: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        firewall = evidence.get("firewall", {})
        if firewall and any(v is False for v in firewall.values()):
            return {
                "cause": "Windows Defender Firewall configuration mismatch or rule blocking",
                "confidence": 0.75,
                "evidence_ids": ["firewall"],
                "missing_evidence": ["firewall_port_rules"],
                "next_checks": ["check_firewall_rules"],
                "recommended_tool_ids": ["collect_network_status"],
                "requires_technician": True,
                "sources": ["KB-NET-008"],
                "summary": "Windows Defender Firewall profile settings or rules may be filtering required application ports."
            }
        return None


class MultipleInterfacesRule(DiagnosticRule):
    rule_id: str = "RULE-NET-009"
    name: str = "Multiple Conflicting Network Interfaces Active"
    description: str = "More than one physical network adapter is active simultaneously causing route confusion."

    def evaluate(self, evidence: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        adapters = evidence.get("adapters_list", [])
        physical_up = [a for a in adapters if not a.get("is_virtual", False) and str(a.get("status", "")).lower() == "up"]
        if len(physical_up) > 1:
            names = [a.get("name", "Adapter") for a in physical_up]
            return {
                "cause": f"Multiple active physical network interfaces detected ({', '.join(names)})",
                "confidence": 0.70,
                "evidence_ids": ["adapters_list"],
                "missing_evidence": ["routing_metric_table"],
                "next_checks": ["renew_dhcp", "flush_dns_cache"],
                "recommended_tool_ids": ["flush_dns_cache"],
                "requires_technician": False,
                "sources": ["KB-NET-009"],
                "summary": f"Simultaneous active connections on {', '.join(names)} may result in route conflicts or DNS leak."
            }
        return None


class HighLatencyPacketLossRule(DiagnosticRule):
    rule_id: str = "RULE-NET-010"
    name: str = "High Latency or Severe Packet Loss"
    description: str = "Network is reachable but experiences > 20% packet loss or > 5000ms latency."

    def evaluate(self, evidence: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        gw_test = evidence.get("gateway_ping", {})
        net_test = evidence.get("internet_ping", {})
        gw_loss = gw_test.get("packet_loss_pct", 0)
        net_loss = net_test.get("packet_loss_pct", 0)
        gw_lat = gw_test.get("avg_latency_ms") or 0
        net_lat = net_test.get("avg_latency_ms") or 0

        if (0 < gw_loss >= 20 and gw_loss < 100) or (0 < net_loss >= 20 and net_loss < 100) or gw_lat > 5000 or net_lat > 5000:
            loss = max(gw_loss, net_loss)
            lat = max(gw_lat, net_lat)
            return {
                "cause": f"Severe network degradation detected ({loss}% packet loss, {lat}ms latency)",
                "confidence": 0.85,
                "evidence_ids": ["gateway_ping", "internet_ping"],
                "missing_evidence": ["wi_fi_rssi_dbm"],
                "next_checks": ["renew_dhcp", "test_gateway"],
                "recommended_tool_ids": ["renew_dhcp"],
                "requires_technician": False,
                "sources": ["KB-NET-010"],
                "summary": f"Intermittent or degraded connection: {loss}% packet loss and {lat}ms response latency."
            }
        return None


class StaticIpConfigurationRule(DiagnosticRule):
    rule_id: str = "RULE-NET-011"
    name: str = "Static IPv4 Configuration Detected (DHCP Disabled)"
    description: str = "Detects manual static IPv4 configuration where DHCP is disabled on the active adapter."

    def evaluate(self, evidence: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        ip_conf = evidence.get("ip_config", {})
        if ip_conf.get("dhcp_enabled") is False:
            adapter_name = ip_conf.get("adapter_name") or evidence.get("network_adapter", {}).get("name", "Wi-Fi")
            ipv4 = ip_conf.get("ipv4_address") or "unassigned"
            gw = ip_conf.get("default_gateway") or "none"
            return {
                "cause": f"Manual static IPv4 configuration detected on '{adapter_name}' (DHCP disabled)",
                "confidence": 0.92,
                "evidence_ids": ["ip_config", "network_adapter"],
                "missing_evidence": ["dhcp_server_lease_offer"],
                "next_checks": ["renew_dhcp", "test_gateway"],
                "recommended_tool_ids": ["renew_dhcp"],
                "requires_technician": False,
                "sources": ["KB-NET-001", "KB-NET-002"],
                "summary": f"Network adapter '{adapter_name}' has DHCP disabled (IP: {ipv4}, Gateway: {gw}). Static IP overrides can break campus/router connectivity and should be restored to automatic DHCP."
            }
        return None


class ManualStaticDnsRule(DiagnosticRule):
    rule_id: str = "RULE-NET-012"
    name: str = "Manual Static DNS Configuration Detected"
    description: str = "Detects manually entered static DNS server addresses instead of automatic DHCP DNS."

    def evaluate(self, evidence: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        ip_conf = evidence.get("ip_config", {})
        dns_test = evidence.get("dns_test", {})
        is_manual_dns = (ip_conf.get("dns_dhcp_enabled") is False) or (dns_test.get("dns_dhcp_enabled") is False)
        if is_manual_dns:
            adapter_name = ip_conf.get("adapter_name") or evidence.get("network_adapter", {}).get("name", "Wi-Fi")
            dns_servers = ip_conf.get("dns_servers") or dns_test.get("dns_servers") or []
            dns_str = ", ".join(dns_servers) if dns_servers else "manual custom servers"
            return {
                "cause": f"Manual static DNS servers configured on '{adapter_name}' ({dns_str})",
                "confidence": 0.90,
                "evidence_ids": ["ip_config", "dns_test"],
                "missing_evidence": ["dhcp_dns_servers"],
                "next_checks": ["flush_dns_cache", "test_dns"],
                "recommended_tool_ids": ["flush_dns_cache"],
                "requires_technician": False,
                "sources": ["KB-NET-003"],
                "summary": f"Adapter '{adapter_name}' is using statically configured DNS servers ({dns_str}) instead of Obtain DNS server address automatically (DHCP). Reset DNS to DHCP and flush the resolver cache."
            }
        return None


class RuleEngine:
    def __init__(self):
        self.rules: List[DiagnosticRule] = [
            AdapterDisconnectedRule(),
            MediaDisconnectedRule(),
            ApipaDhcpFailureRule(),
            StaticIpConfigurationRule(),
            GatewayUnreachableRule(),
            HighLatencyPacketLossRule(),
            InternetWanLostRule(),
            DnsResolutionFailureRule(),
            ManualStaticDnsRule(),
            FirewallBlockedRule(),
            MultipleInterfacesRule(),
            CaptivePortalRule(),
            PrintSpoolerStoppedRule(),
        ]

    def evaluate(self, evidence: Dict[str, Any]) -> DiagnosisResult:
        hypotheses: List[HypothesisItem] = []
        recommended_tools: List[str] = []
        sources: List[str] = []
        summaries: List[str] = []
        requires_tech = False

        for rule in self.rules:
            result = rule.evaluate(evidence)
            if result:
                hypotheses.append(HypothesisItem(
                    cause=result["cause"],
                    confidence=result["confidence"],
                    evidence_ids=result["evidence_ids"],
                    missing_evidence=result.get("missing_evidence", []),
                    next_checks=result.get("next_checks", [])
                ))
                for t in result.get("recommended_tool_ids", []):
                    if t not in recommended_tools:
                        recommended_tools.append(t)
                for s in result.get("sources", []):
                    if s not in sources:
                        sources.append(s)
                summaries.append(result["summary"])
                if result.get("requires_technician", False):
                    requires_tech = True

        if not hypotheses:
            return DiagnosisResult(
                status="insufficient_evidence",
                summary="Deterministic diagnostic rules evaluated evidence but found no clear match. Technician investigation or AI reasoning is recommended.",
                hypotheses=[],
                recommended_tool_ids=["collect_network_status", "test_gateway"],
                requires_technician=True,
                sources=[],
                is_fallback=False,
                provider="rule_engine"
            )

        overall_summary = " ".join(summaries)
        return DiagnosisResult(
            status="hypotheses",
            summary=overall_summary,
            hypotheses=hypotheses,
            recommended_tool_ids=recommended_tools,
            requires_technician=requires_tech,
            sources=sources,
            is_fallback=False,
            provider="rule_engine"
        )


rule_engine = RuleEngine()
