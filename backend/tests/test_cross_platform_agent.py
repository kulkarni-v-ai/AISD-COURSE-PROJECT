import platform
from unittest.mock import patch, MagicMock
import pytest

from agent_config import _detect_os_info
from diagnostics import (
    EndpointDiagnostics,
    _prefix_length_to_netmask,
    _is_linux,
    _linux_ping
)
from remediation import LocalRemediationPolicy, LocalRemediationExecutor
from chatbot_client import answer_offline


def test_cross_platform_os_detection():
    """Verify dynamic OS detection returns proper prefix and release name."""
    with patch("platform.system", return_value="Linux"):
        with patch("platform.release", return_value="5.15.0-generic"):
            os_name, os_version, prefix = _detect_os_info()
            assert os_name == "Linux"
            assert prefix == "lnx"
            assert "Linux" in os_version

    with patch("platform.system", return_value="Windows"):
        with patch("platform.release", return_value="11"):
            with patch("platform.version", return_value="10.0.22631"):
                os_name, os_version, prefix = _detect_os_info()
                assert os_name == "Windows"
                assert prefix == "win"


def test_prefix_length_to_netmask():
    assert _prefix_length_to_netmask(24) == "255.255.255.0"
    assert _prefix_length_to_netmask(16) == "255.255.0.0"
    assert _prefix_length_to_netmask(32) == "255.255.255.255"
    assert _prefix_length_to_netmask(None) is None


def test_linux_service_policy_allowlist():
    """Verify Linux services (cups, systemd-resolved, NetworkManager) are approved in policy."""
    spec = LocalRemediationPolicy.ALLOWLISTED_TOOLS["restart_approved_service"]
    allowed = spec["allowed_services"]
    assert "cups" in allowed
    assert "systemd-resolved" in allowed
    assert "NetworkManager" in allowed

    ok, reason = LocalRemediationPolicy.check_policy("restart_approved_service", {"service_name": "cups"})
    assert ok is True

    bad_ok, bad_reason = LocalRemediationPolicy.check_policy("restart_approved_service", {"service_name": "malicious_service"})
    assert bad_ok is False


def test_linux_mock_and_real_remediation_dispatch():
    """Verify Linux commands dispatch properly in LocalRemediationExecutor."""
    with patch("platform.system", return_value="Linux"):
        with patch("subprocess.run") as mock_sub:
            mock_sub.return_value = MagicMock(returncode=0, stdout="active\n", stderr="")
            ok, output, verif = LocalRemediationExecutor.execute(
                "restart_approved_service",
                {"service_name": "cups"},
                is_mock=False
            )
            assert ok is True
            assert verif == "VERIFIED_RESOLVED"


def test_offline_chatbot_advisor():
    """Verify offline chatbot advisor provides grounded SOP guidance when server is unreachable."""
    res_dhcp = answer_offline("I have a 169.254 APIPA address and no internet")
    assert "KB-NET-001" in res_dhcp["reply"]
    assert "renew_dhcp" in res_dhcp["reply"]

    res_dns = answer_offline("DNS resolution failed for intranet domain")
    assert "KB-NET-003" in res_dns["reply"]
    assert "flush_dns_cache" in res_dns["reply"]

    res_print = answer_offline("Workstation cannot print, spooler is stopped")
    assert "KB-PRT-001" in res_print["reply"]
