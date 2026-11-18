import pytest
import os
import json
from pathlib import Path
from storage import AgentLocalStorage
from rules import local_rule_engine
from remediation import LocalRemediationExecutor


@pytest.fixture
def temp_storage(tmp_path):
    db_file = tmp_path / "test_agent.db"
    return AgentLocalStorage(str(db_file))


def test_storage_queue_and_get(temp_storage):
    payload = {"incident_number": "INC-TEST-001", "title": "Test Wi-Fi outage"}
    ev_uuid = temp_storage.queue_event("INCIDENT_REPORTED", payload)
    
    pending = temp_storage.get_pending_events()
    assert len(pending) == 1
    assert pending[0]["event_uuid"] == ev_uuid
    assert pending[0]["payload"]["incident_number"] == "INC-TEST-001"


def test_storage_mark_synced(temp_storage):
    payload = {"test": "data"}
    ev_uuid = temp_storage.queue_event("TEST_EVENT", payload)
    
    assert len(temp_storage.get_pending_events()) == 1
    temp_storage.mark_events_synced([ev_uuid])
    assert len(temp_storage.get_pending_events()) == 0


def test_local_rules_apipa():
    evidence = {
        "ip_config": {
            "ipv4_address": "169.254.100.22",
            "default_gateway": None,
            "dhcp_enabled": True
        }
    }
    result = local_rule_engine.evaluate(evidence)
    assert result["status"] == "hypotheses"
    assert "renew_dhcp" in result["recommended_tool_ids"]
    assert "KB-NET-001" in result["sources"]


def test_local_remediation_mock():
    success, output, verification = LocalRemediationExecutor.execute(
        tool_id="renew_dhcp",
        arguments={"adapter_name": "Wi-Fi"},
        is_mock=True
    )
    assert success is True
    assert "MOCK ENDPOINT EXECUTION" in output
    assert verification == "VERIFIED_RESOLVED"


def test_failure_condition_1_no_adapter_available():
    evidence = {
        "network_adapter": {"name": "Wi-Fi", "status": "Disabled"},
        "adapters_list": [{"name": "Wi-Fi", "status": "Disabled", "is_virtual": False}],
        "ip_config": {"ipv4_address": None, "default_gateway": None}
    }
    result = local_rule_engine.evaluate(evidence)
    assert result["status"] == "hypotheses"
    assert any("adapter disabled" in h["cause"].lower() for h in result["hypotheses"])
    assert "enable_adapter" in result["recommended_tool_ids"]


def test_failure_condition_2_cable_wifi_disconnected():
    evidence = {
        "network_adapter": {"name": "Ethernet", "status": "Disconnected", "media_state": 2},
        "ip_config": {"ipv4_address": None, "default_gateway": None}
    }
    result = local_rule_engine.evaluate(evidence)
    assert result["status"] == "hypotheses"
    assert any("unplugged" in h["cause"].lower() or "lost" in h["cause"].lower() for h in result["hypotheses"])
    assert "KB-NET-006" in result["sources"]


def test_failure_condition_4_gateway_unreachable():
    evidence = {
        "network_adapter": {"name": "Wi-Fi", "status": "Up"},
        "ip_config": {"ipv4_address": "192.168.1.10", "default_gateway": "192.168.1.1"},
        "gateway_ping": {"reachable": False, "packet_loss_pct": 100}
    }
    result = local_rule_engine.evaluate(evidence)
    assert result["status"] == "hypotheses"
    assert any("gateway unreachable" in h["cause"].lower() for h in result["hypotheses"])
    assert "renew_dhcp" in result["recommended_tool_ids"]


def test_failure_condition_5_dns_failure():
    evidence = {
        "network_adapter": {"name": "Wi-Fi", "status": "Up"},
        "ip_config": {"ipv4_address": "192.168.1.10", "default_gateway": "192.168.1.1"},
        "gateway_ping": {"reachable": True, "packet_loss_pct": 0},
        "internet_ping": {"reachable": True, "packet_loss_pct": 0},
        "dns_test": {"resolved": False, "target_domain": "google.com"}
    }
    result = local_rule_engine.evaluate(evidence)
    assert result["status"] == "hypotheses"
    assert any("dns resolver failure" in h["cause"].lower() for h in result["hypotheses"])
    assert "flush_dns_cache" in result["recommended_tool_ids"]


def test_failure_condition_6_internet_lost_wan_outage():
    evidence = {
        "network_adapter": {"name": "Wi-Fi", "status": "Up"},
        "ip_config": {"ipv4_address": "192.168.1.10", "default_gateway": "192.168.1.1"},
        "gateway_ping": {"reachable": True, "packet_loss_pct": 0},
        "internet_ping": {"reachable": False, "packet_loss_pct": 100}
    }
    result = local_rule_engine.evaluate(evidence)
    assert result["status"] == "hypotheses"
    assert any("internet wan connection lost" in h["cause"].lower() for h in result["hypotheses"])
    assert "KB-NET-007" in result["sources"]


def test_failure_condition_9_high_latency_packet_loss():
    evidence = {
        "network_adapter": {"name": "Wi-Fi", "status": "Up"},
        "ip_config": {"ipv4_address": "192.168.1.10", "default_gateway": "192.168.1.1"},
        "gateway_ping": {"reachable": True, "packet_loss_pct": 50, "avg_latency_ms": 6200},
        "internet_ping": {"reachable": True, "packet_loss_pct": 50, "avg_latency_ms": 6500}
    }
    result = local_rule_engine.evaluate(evidence)
    assert result["status"] == "hypotheses"
    assert any("degradation" in h["cause"].lower() for h in result["hypotheses"])
    assert "KB-NET-010" in result["sources"]


def test_static_ip_and_manual_dns_rules_and_verification():
    from remediation import LocalVerifier

    static_evidence = {
        "network_adapter": {"name": "Wi-Fi 2", "status": "Up"},
        "ip_config": {
            "adapter_name": "Wi-Fi 2",
            "ipv4_address": "192.168.1.99",
            "default_gateway": "192.168.1.1",
            "dhcp_enabled": False,
            "dns_dhcp_enabled": False,
            "dns_servers": ["8.8.8.8", "8.8.8.4"],
        },
        "gateway_ping": {"reachable": True, "packet_loss_pct": 0},
        "dns_test": {"resolved": True, "dns_dhcp_enabled": False},
    }
    res = local_rule_engine.evaluate(static_evidence)
    assert res["status"] == "hypotheses"
    assert "renew_dhcp" in res["recommended_tool_ids"]
    assert "flush_dns_cache" in res["recommended_tool_ids"]

    # Verification fails if static IP remains
    v_fail, _ = LocalVerifier.verify(
        rule_engine=local_rule_engine,
        initial_hypothesis_cause="Manual static IPv4 configuration detected on 'Wi-Fi 2' (DHCP disabled)",
        fresh_evidence=static_evidence,
        is_mock=False,
    )
    assert v_fail == "not_resolved"

    # Verification succeeds once DHCP and automatic DNS are restored
    fixed_evidence = {
        "network_adapter": {"name": "Wi-Fi 2", "status": "Up"},
        "ip_config": {
            "adapter_name": "Wi-Fi 2",
            "ipv4_address": "10.63.1.84",
            "default_gateway": "10.63.0.1",
            "dhcp_enabled": True,
            "dns_dhcp_enabled": True,
            "dns_servers": ["10.63.0.1"],
        },
        "gateway_ping": {"reachable": True, "packet_loss_pct": 0},
        "dns_test": {"resolved": True, "dns_dhcp_enabled": True},
    }
    v_ok, _ = LocalVerifier.verify(
        rule_engine=local_rule_engine,
        initial_hypothesis_cause="Manual static IPv4 configuration detected on 'Wi-Fi 2' (DHCP disabled)",
        fresh_evidence=fixed_evidence,
        is_mock=False,
    )
    assert v_ok == "resolved"


def test_elevated_ps_encoding_handles_spaces_and_quotes():
    import base64
    from remediation import _build_encoded_ps, _ps_quote

    adapter = "Wi-Fi 2"
    inner = f"$iface = {_ps_quote(adapter)}; & netsh.exe interface ipv4 set dnsservers ('name=' + $iface) source=dhcp"
    b64 = _build_encoded_ps(inner)
    decoded = base64.b64decode(b64).decode("utf-16-le")
    assert "Wi-Fi 2" in decoded
    assert "netsh.exe interface ipv4 set dnsservers" in decoded


def test_rules_detect_dhcp_service_and_missing_ip_on_up_adapter():
    evidence = {
        "network_adapter": {"name": "Wi-Fi 2", "status": "Up"},
        "ip_config": {"adapter_name": "Wi-Fi 2", "ipv4_address": None, "default_gateway": None, "dhcp_enabled": True, "has_valid_ip": False},
        "services": {"Dhcp": {"status": "Stopped"}, "Dnscache": {"status": "Running"}, "Spooler": {"status": "Running"}},
    }
    res = local_rule_engine.evaluate(evidence)
    assert res["status"] == "hypotheses"
    assert "renew_dhcp" in res["recommended_tool_ids"]
    assert "restart_approved_service" in res["recommended_tool_ids"]
    assert res["recommended_tool_ids"][0] in ("renew_dhcp", "restart_approved_service")

