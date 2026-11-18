import pytest
from app.rules.engine import rule_engine


def test_apipa_rule_match():
    evidence = {
        "ip_config": {
            "ipv4_address": "169.254.45.67",
            "default_gateway": None,
            "dhcp_enabled": True
        }
    }
    result = rule_engine.evaluate(evidence)
    assert result.status == "hypotheses"
    assert len(result.hypotheses) > 0
    assert "DHCP" in result.hypotheses[0].cause
    assert "renew_dhcp" in result.recommended_tool_ids
    assert "KB-NET-001" in result.sources


def test_gateway_unreachable_rule_match():
    evidence = {
        "ip_config": {
            "ipv4_address": "10.0.1.15",
            "default_gateway": "10.0.1.1"
        },
        "gateway_ping": {
            "reachable": False,
            "packet_loss_pct": 100
        }
    }
    result = rule_engine.evaluate(evidence)
    assert result.status == "hypotheses"
    assert any("gateway unreachable" in h.cause.lower() for h in result.hypotheses)
    assert "test_gateway" in result.recommended_tool_ids


def test_dns_failure_rule_match():
    evidence = {
        "ip_config": {
            "ipv4_address": "10.0.1.15",
            "default_gateway": "10.0.1.1"
        },
        "gateway_ping": {
            "reachable": True,
            "packet_loss_pct": 0
        },
        "dns_test": {
            "resolved": False,
            "target_domain": "intranet.college.edu"
        }
    }
    result = rule_engine.evaluate(evidence)
    assert result.status == "hypotheses"
    assert any("dns" in h.cause.lower() for h in result.hypotheses)
    assert "flush_dns_cache" in result.recommended_tool_ids


def test_print_spooler_stopped():
    evidence = {
        "services": {
            "Spooler": {"status": "Stopped"}
        }
    }
    result = rule_engine.evaluate(evidence)
    assert result.status == "hypotheses"
    assert any("spooler" in h.cause.lower() for h in result.hypotheses)
    assert "restart_approved_service" in result.recommended_tool_ids


def test_healthy_network_returns_insufficient_evidence():
    evidence = {
        "ip_config": {
            "ipv4_address": "10.0.1.15",
            "default_gateway": "10.0.1.1"
        },
        "gateway_ping": {
            "reachable": True,
            "packet_loss_pct": 0
        },
        "dns_test": {
            "resolved": True
        }
    }
    result = rule_engine.evaluate(evidence)
    assert result.status == "insufficient_evidence"
    assert result.requires_technician is True
