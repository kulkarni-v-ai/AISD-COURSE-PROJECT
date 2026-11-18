from unittest.mock import patch
import pytest

from app.core.config import settings
from app.remediation import windows_net
from app.remediation.executor import remediation_executor
from app.remediation.verifier import verification_engine
from app.rules.engine import rule_engine


def test_ollama_llama_8b_config_loaded():
    assert settings.OLLAMA_MODEL == "llama3.1:8b"
    assert settings.OLLAMA_TIMEOUT_SECONDS >= 60


def test_resolve_active_adapter_falls_back_from_wifi_to_wifi_2():
    adapters = [
        {"name": "vEthernet (WSL)", "description": "Hyper-V Virtual Ethernet Adapter", "status": "Up", "is_virtual": True},
        {"name": "Ethernet", "description": "Realtek PCIe GbE Family Controller", "status": "Disconnected", "is_virtual": False},
        {"name": "Wi-Fi 2", "description": "Realtek RTL8852BE WiFi 6", "status": "Up", "is_virtual": False},
    ]
    assert windows_net.resolve_active_adapter("Wi-Fi", adapters=adapters) == "Wi-Fi 2"
    assert windows_net.resolve_active_adapter(None, adapters=adapters) == "Wi-Fi 2"
    assert windows_net.resolve_active_adapter("Ethernet", adapters=adapters) == "Ethernet"


def test_parse_netsh_dns_output_static_vs_dhcp():
    static_raw = """
Configuration for interface "Wi-Fi 2"
    Statically Configured DNS Servers:    8.8.8.8
                                          8.8.8.4
    Register with which suffix:           Primary only
"""
    parsed_static = windows_net.parse_netsh_dns_output(static_raw)
    assert parsed_static["static_dns_configured"] is True
    assert parsed_static["dns_dhcp_enabled"] is False
    assert parsed_static["dns_servers"] == ["8.8.8.8", "8.8.8.4"]

    dhcp_raw = """
Configuration for interface "Wi-Fi 2"
    DNS servers configured through DHCP:  10.63.0.1
    Register with which suffix:           Primary only
"""
    parsed_dhcp = windows_net.parse_netsh_dns_output(dhcp_raw)
    assert parsed_dhcp["static_dns_configured"] is False
    assert parsed_dhcp["dns_dhcp_enabled"] is True
    assert parsed_dhcp["dns_servers"] == ["10.63.0.1"]


def test_rules_detect_static_ip_and_manual_dns():
    evidence = {
        "network_adapter": {"name": "Wi-Fi 2", "status": "Up"},
        "ip_config": {
            "adapter_name": "Wi-Fi 2",
            "ipv4_address": "10.63.1.84",
            "default_gateway": "10.63.0.1",
            "dhcp_enabled": False,
            "dns_dhcp_enabled": False,
            "dns_servers": ["8.8.8.8", "8.8.8.4"],
        },
        "gateway_ping": {"reachable": True, "packet_loss_pct": 0},
        "dns_test": {"resolved": True, "dns_dhcp_enabled": False},
    }
    res = rule_engine.evaluate(evidence)
    assert res.status == "hypotheses"
    assert "renew_dhcp" in res.recommended_tool_ids
    assert "flush_dns_cache" in res.recommended_tool_ids


@pytest.mark.asyncio
async def test_verifier_ip_validity_fails_when_static_ip_remains():
    with patch("app.remediation.windows_net.resolve_active_adapter", return_value="Wi-Fi 2"), \
         patch("app.remediation.windows_net.get_ip_config_for_adapter", return_value={
             "adapter_name": "Wi-Fi 2",
             "ipv4_address": "192.168.1.99",
             "default_gateway": "192.168.1.1",
             "dhcp_enabled": False,
             "dns_dhcp_enabled": True,
             "static_dns_configured": False,
             "dns_servers": ["192.168.1.1"],
         }), \
         patch("app.remediation.windows_net.ping_host", return_value={"reachable": True, "avg_latency_ms": 2}):
        v_status, v_ev = await verification_engine.verify(
            tool_id="renew_dhcp",
            verification_type="ip_validity",
            arguments={"adapter_name": "Wi-Fi"},
            is_mock=False,
        )
        assert v_status == "NOT_RESOLVED"
        assert "Static IP" in v_ev.get("reason", "")


@pytest.mark.asyncio
async def test_verifier_ip_validity_succeeds_when_dhcp_restored():
    with patch("app.remediation.windows_net.resolve_active_adapter", return_value="Wi-Fi 2"), \
         patch("app.remediation.windows_net.get_ip_config_for_adapter", return_value={
             "adapter_name": "Wi-Fi 2",
             "ipv4_address": "10.63.1.84",
             "subnet_mask": "255.255.240.0",
             "default_gateway": "10.63.0.1",
             "dhcp_enabled": True,
             "dns_dhcp_enabled": True,
             "static_dns_configured": False,
             "dns_servers": ["10.63.0.1"],
         }), \
         patch("app.remediation.windows_net.ping_host", return_value={"reachable": True, "avg_latency_ms": 5}):
        v_status, v_ev = await verification_engine.verify(
            tool_id="renew_dhcp",
            verification_type="ip_validity",
            arguments={"adapter_name": "Wi-Fi"},
            is_mock=False,
        )
        assert v_status == "VERIFIED_RESOLVED"
        assert v_ev["adapter_name"] == "Wi-Fi 2"
        assert v_ev["dhcp_enabled"] is True


@pytest.mark.asyncio
async def test_verifier_dns_resolve_fails_when_static_dns_still_configured():
    with patch("app.remediation.windows_net.resolve_active_adapter", return_value="Wi-Fi 2"), \
         patch("app.remediation.windows_net.get_dns_server_config", return_value={
             "dns_dhcp_enabled": False,
             "static_dns_configured": True,
             "dns_servers": ["8.8.8.8", "8.8.8.4"],
         }), \
         patch("app.remediation.windows_net.test_dns_hosts", return_value={"resolved": True, "domains": {"google.com": {"resolved": True}}}):
        v_status, v_ev = await verification_engine.verify(
            tool_id="flush_dns_cache",
            verification_type="dns_resolve",
            arguments={"adapter_name": "Wi-Fi"},
            is_mock=False,
        )
        assert v_status == "NOT_RESOLVED"
        assert v_ev["static_dns_configured"] is True


@pytest.mark.asyncio
async def test_executor_flags_failure_if_static_dns_cannot_be_cleared():
    with patch("app.remediation.windows_net.reset_dns_to_dhcp_and_flush", return_value={
        "success": False,
        "exit_code": 1,
        "adapter_name": "Wi-Fi 2",
        "output": "Pre-remediation DNS mode: Static (8.8.8.8, 8.8.8.4)",
        "error": "Static DNS servers are still configured on 'Wi-Fi 2'. Windows Administrator privileges required.",
    }):
        exec_status, code, out, err, v_status, _ = await remediation_executor.execute(
            tool_id="flush_dns_cache",
            arguments={"adapter_name": "Wi-Fi"},
            is_mock=False,
        )
        assert exec_status == "FAILED"
        assert code == 1
        assert v_status == "NOT_RESOLVED"
        assert "Administrator" in err
