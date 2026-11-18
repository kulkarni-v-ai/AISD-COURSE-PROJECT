import pytest
import uuid
import json
from unittest.mock import patch, MagicMock
from storage import AgentLocalStorage
from rules import local_rule_engine
from remediation import LocalRemediationExecutor, LocalRemediationPolicy, LocalVerifier
from agent import run_offline_workflow
from sync import EndpointSyncService


@pytest.fixture
def temp_storage(tmp_path):
    db_file = tmp_path / "test_offline.db"
    return AgentLocalStorage(str(db_file))


def test_remediation_policy_allowlist():
    """Verify that only explicitly allowlisted actions are permitted."""
    # Allowlisted tools
    ok, _ = LocalRemediationPolicy.check_policy("enable_adapter", {"adapter_name": "Wi-Fi 2"})
    assert ok is True

    ok, _ = LocalRemediationPolicy.check_policy("renew_dhcp", {"adapter_name": "Wi-Fi"})
    assert ok is True

    ok, _ = LocalRemediationPolicy.check_policy("flush_dns_cache")
    assert ok is True

    ok, _ = LocalRemediationPolicy.check_policy("restart_approved_service", {"service_name": "Spooler"})
    assert ok is True

    ok, _ = LocalRemediationPolicy.check_policy("restart_approved_service", {"service_name": "Dhcp"})
    assert ok is True

    ok, _ = LocalRemediationPolicy.check_policy("restart_approved_service", {"service_name": "Dnscache"})
    assert ok is True

    # Disallowed tools and arbitrary commands
    ok, reason = LocalRemediationPolicy.check_policy("format_c_drive")
    assert ok is False
    assert "not in the allowlist" in reason

    ok, reason = LocalRemediationPolicy.check_policy("custom_shell_script")
    assert ok is False

    # Disallowed service for restart
    ok, reason = LocalRemediationPolicy.check_policy("restart_approved_service", {"service_name": "WindowsUpdate"})
    assert ok is False
    assert "not approved for local restart" in reason


def test_remediation_safeguards_cooldown_and_retries(temp_storage):
    """Test retry threshold and cooldown safeguards."""
    issue_key = "DHCP lease acquisition failure (APIPA 169.254.x.x assigned)"
    
    # 1. Record 3 failed attempts
    for _ in range(3):
        temp_storage.record_remediation_attempt(issue_key, "renew_dhcp", success=False, verification_status="not_resolved")
    
    assert temp_storage.get_failed_remediation_count(issue_key) == 3
    assert temp_storage.get_recent_remediation_attempts(issue_key, within_seconds=60) == 3

    # Reset with a successful resolution
    temp_storage.record_remediation_attempt(issue_key, "renew_dhcp", success=True, verification_status="resolved")
    assert temp_storage.get_failed_remediation_count(issue_key) == 0


def test_scenario_a_offline_known_issue_successful_fix(temp_storage):
    """
    Scenario A: Offline + Known Issue + Successful Fix
    No server connection
    -> Local diagnostics detect known issue (APIPA)
    -> Rule matches (renew_dhcp)
    -> Approved remediation executes
    -> Verification succeeds
    -> Result stored locally in SQLite outbox
    """
    apipa_evidence = {
        "ip_config": {
            "ipv4_address": "169.254.55.12",
            "default_gateway": None,
            "dhcp_enabled": True
        },
        "network_adapter": {"name": "Wi-Fi", "status": "Up"},
        "gateway_ping": {"reachable": False, "packet_loss_pct": 100},
        "dns_test": {"resolved": False},
        "services": {"Spooler": {"status": "Running"}}
    }

    result = run_offline_workflow(
        storage=temp_storage,
        telemetry_override=apipa_evidence,
        is_mock=True,
        simulate_remediation_success=True,
        simulate_verification_outcome="resolved",
        force=True
    )

    assert result["status"] == "RESOLVED"
    assert result["remediation_result"] is True
    assert result["verification_result"] == "resolved"
    assert "DHCP lease acquisition failure" in result["detected_issue"]
    assert result["recommended_action"] == "renew_dhcp"

    # Verify event stored in SQLite outbox
    pending = temp_storage.get_pending_events()
    assert len(pending) == 1
    stored_ev = pending[0]
    assert stored_ev["event_type"] == "OFFLINE_REMEDIATION_SUCCESS"
    assert stored_ev["payload"]["final_local_status"] == "RESOLVED"
    assert stored_ev["payload"]["verification_result"] == "resolved"
    assert stored_ev["payload"]["recommended_action"] == "renew_dhcp"
    assert stored_ev["payload"]["remediation_attempted"] is True


def test_scenario_b_offline_known_issue_failed_fix(temp_storage):
    """
    Scenario B: Offline + Known Issue + Failed Fix
    No server connection
    -> Local diagnostics detect known issue
    -> Rule matches
    -> Remediation executes or fails
    -> Verification shows unresolved
    -> Failure / escalation event stored locally
    """
    apipa_evidence = {
        "ip_config": {
            "ipv4_address": "169.254.88.99",
            "default_gateway": None,
            "dhcp_enabled": True
        },
        "network_adapter": {"name": "Wi-Fi", "status": "Up"},
        "gateway_ping": {"reachable": False, "packet_loss_pct": 100},
        "dns_test": {"resolved": False},
        "services": {"Spooler": {"status": "Running"}}
    }

    result = run_offline_workflow(
        storage=temp_storage,
        telemetry_override=apipa_evidence,
        is_mock=True,
        simulate_remediation_success=False,  # Command fails
        simulate_verification_outcome="not_resolved",
        force=True
    )

    assert result["status"] == "ESCALATED"
    assert result["remediation_result"] is False
    assert result["verification_result"] == "not_resolved"

    # Verify failure/escalation event queued in SQLite
    pending = temp_storage.get_pending_events()
    assert len(pending) == 1
    stored_ev = pending[0]
    assert stored_ev["event_type"] == "OFFLINE_REMEDIATION_FAILED"
    assert stored_ev["payload"]["final_local_status"] == "ESCALATED"
    assert stored_ev["payload"]["verification_result"] == "not_resolved"
    assert stored_ev["payload"]["remediation_attempted"] is True


def test_scenario_c_offline_unknown_issue(temp_storage):
    """
    Scenario C: Offline + Unknown Issue
    No server connection
    -> Diagnostics run
    -> No local rule matches (healthy or unrecognized anomaly)
    -> No remediation executed
    -> Diagnostic result is queued for later server-side analysis
    """
    healthy_telemetry = {
        "ip_config": {
            "ipv4_address": "10.0.0.45",
            "default_gateway": "10.0.0.1",
            "dhcp_enabled": True
        },
        "network_adapter": {"name": "Ethernet", "status": "Up"},
        "gateway_ping": {"reachable": True, "packet_loss_pct": 0},
        "dns_test": {"resolved": True, "resolved_ip": "10.0.0.10"},
        "services": {"Spooler": {"status": "Running"}, "Dhcp": {"status": "Running"}}
    }

    result = run_offline_workflow(
        storage=temp_storage,
        telemetry_override=healthy_telemetry,
        is_mock=True,
        force=True
    )

    assert result["status"] == "ANALYSIS_QUEUED"
    assert result["payload"]["remediation_attempted"] is False
    assert result["payload"]["detected_issue"] is None
    assert result["payload"]["recommended_action"] is None

    # Stored locally for later server synchronization
    pending = temp_storage.get_pending_events()
    assert len(pending) == 1
    assert pending[0]["event_type"] == "DIAGNOSTIC_COLLECTED"
    assert pending[0]["payload"]["final_local_status"] == "ANALYSIS_QUEUED"


def test_scenario_d_connectivity_returns(temp_storage):
    """
    Scenario D: Connectivity Returns
    Offline events exist in SQLite
    -> Server becomes reachable
    -> Existing synchronization runs
    -> Events synchronize successfully
    -> No duplicate events are created
    """
    # 1. Populate outbox with an offline remediation event
    ev_uuid1 = str(uuid.uuid4())
    temp_storage.queue_event(
        event_type="OFFLINE_REMEDIATION_SUCCESS",
        payload={
            "event_uuid": ev_uuid1,
            "detected_issue": "DHCP lease failure",
            "remediation_result": True,
            "verification_result": "resolved",
            "final_local_status": "RESOLVED"
        },
        event_uuid=ev_uuid1
    )

    assert len(temp_storage.get_pending_events()) == 1

    sync_svc = EndpointSyncService(temp_storage)

    # 2. Simulate server reachable & batch sync endpoint response
    def fake_post(url, json=None, **kwargs):
        class FakeResponse:
            status_code = 200
            def json(self):
                # Server acknowledges ev_uuid1
                return {
                    "accepted_uuids": [ev_uuid1],
                    "duplicate_uuids": [],
                    "rejected_uuids": []
                }
        return FakeResponse()

    with patch.object(sync_svc, "is_server_reachable", return_value=True):
        with patch("httpx.Client.post", side_effect=fake_post):
            accepted, duplicate = sync_svc.sync_outbox()
            assert accepted == 1
            assert duplicate == 0

    # 3. Events should now be marked SYNCED in SQLite
    assert len(temp_storage.get_pending_events()) == 0

    # 4. Attempting another sync should find 0 pending events (idempotent deduplication)
    with patch.object(sync_svc, "is_server_reachable", return_value=True):
        accepted2, dup2 = sync_svc.sync_outbox()
        assert accepted2 == 0
        assert dup2 == 0


def test_offline_disabled_adapter_and_gateway_unreachable(temp_storage):
    """Disabled adapters run enable_adapter and gateway failures run renew_dhcp instead of rejecting test_gateway."""
    disabled_telemetry = {
        "network_adapter": {"name": "Wi-Fi 2", "status": "Disabled"},
        "adapters_list": [{"name": "Wi-Fi 2", "status": "Disabled", "is_virtual": False}],
        "ip_config": {"adapter_name": "Wi-Fi 2", "ipv4_address": None, "default_gateway": None},
    }
    res1 = run_offline_workflow(
        storage=temp_storage,
        telemetry_override=disabled_telemetry,
        is_mock=True,
        simulate_remediation_success=True,
        simulate_verification_outcome="resolved",
        force=True,
    )
    assert res1["status"] == "RESOLVED"
    assert res1["recommended_action"] == "enable_adapter"

    gw_telemetry = {
        "network_adapter": {"name": "Wi-Fi 2", "status": "Up"},
        "ip_config": {"adapter_name": "Wi-Fi 2", "ipv4_address": "10.63.1.84", "default_gateway": "10.63.0.1", "dhcp_enabled": True},
        "gateway_ping": {"reachable": False, "packet_loss_pct": 100},
        "dns_test": {"resolved": True, "dns_dhcp_enabled": True},
    }
    res2 = run_offline_workflow(
        storage=temp_storage,
        telemetry_override=gw_telemetry,
        is_mock=True,
        simulate_remediation_success=True,
        simulate_verification_outcome="resolved",
        force=True,
    )
    assert res2["status"] == "RESOLVED"
    assert res2["recommended_action"] == "renew_dhcp"


def test_offline_physical_disconnect_escalates_and_multi_issue_runs_all_tools(temp_storage):
    """Physical cable unplug escalates cleanly without POLICY_REJECTED; Static IP+DNS+Dhcp runs all steps."""
    unplugged = {
        "network_adapter": {"name": "Ethernet", "status": "Disconnected", "media_state": 2},
        "ip_config": {"adapter_name": "Ethernet", "ipv4_address": None, "default_gateway": None},
    }
    esc = run_offline_workflow(storage=temp_storage, telemetry_override=unplugged, is_mock=True, force=True)
    assert esc["status"] == "ESCALATED"
    assert esc["resolution_flag"] == "CANNOT_BE_DONE_FLAGGED"

    multi_issue = {
        "network_adapter": {"name": "Wi-Fi 2", "status": "Up"},
        "ip_config": {
            "adapter_name": "Wi-Fi 2",
            "ipv4_address": "192.168.1.99",
            "default_gateway": "192.168.1.1",
            "dhcp_enabled": False,
            "dns_dhcp_enabled": False,
            "dns_servers": ["8.8.8.8"],
        },
        "gateway_ping": {"reachable": True, "packet_loss_pct": 0},
        "dns_test": {"resolved": False, "dns_dhcp_enabled": False},
        "services": {"Dhcp": {"status": "Stopped"}, "Spooler": {"status": "Running"}},
    }
    res_multi = run_offline_workflow(
        storage=temp_storage,
        telemetry_override=multi_issue,
        is_mock=True,
        simulate_remediation_success=True,
        simulate_verification_outcome="resolved",
        force=True,
    )
    assert res_multi["status"] == "RESOLVED"
    executed_names = [a["tool_id"] for a in res_multi["executed_actions"]]
    assert "restart_approved_service" in executed_names
    assert "renew_dhcp" in executed_names
    assert "flush_dns_cache" in executed_names
    srv_step = next(a for a in res_multi["executed_actions"] if a["tool_id"] == "restart_approved_service")
    assert srv_step["arguments"]["service_name"] == "Dhcp"


def test_offline_disallowed_tool_still_rejected_by_policy(temp_storage):
    class FakeEvilRuleEngine:
        def evaluate(self, _evidence):
            return {
                "status": "hypotheses",
                "hypotheses": [{"cause": "Corrupted disk", "confidence": 0.9, "next_checks": ["format_c_drive"]}],
                "recommended_tool_ids": ["format_c_drive"],
                "sources": ["KB-EVIL"],
            }

    res = run_offline_workflow(
        storage=temp_storage,
        telemetry_override={"ip_config": {}},
        rule_engine=FakeEvilRuleEngine(),
        is_mock=True,
        force=True,
    )
    assert res["status"] == "POLICY_REJECTED"


def test_stale_remediation_failures_expire_after_window(temp_storage):
    import sqlite3
    issue = "DNS resolver failure or stale cache"
    with sqlite3.connect(temp_storage.db_path) as conn:
        for _ in range(3):
            conn.execute(
                "INSERT INTO remediation_history (issue_key, tool_id, success, verification_status, attempted_at) "
                "VALUES (?, 'flush_dns_cache', 1, 'not_resolved', '2026-01-01T00:00:00+00:00')",
                (issue,),
            )
        conn.commit()
    assert temp_storage.get_failed_remediation_count(issue, within_seconds=900) == 0
    assert temp_storage.get_failed_remediation_count(issue, within_seconds=None) == 3


def test_offline_workflow_includes_decision_trace_and_remote_task_executes(temp_storage):
    from agent import execute_remote_task
    from agent_config import agent_config

    healthy = {
        "network_adapter": {"name": "Wi-Fi 2", "status": "Up", "mac_address": "AA:BB:CC:DD:EE:FF"},
        "ip_config": {
            "adapter_name": "Wi-Fi 2",
            "ipv4_address": "10.63.1.84",
            "default_gateway": "10.63.0.1",
            "dhcp_enabled": True,
            "dns_dhcp_enabled": True,
            "dns_servers": ["10.63.0.1"],
        },
        "gateway_ping": {"reachable": True, "packet_loss_pct": 0, "avg_latency_ms": 3},
        "internet_ping": {"reachable": True, "packet_loss_pct": 0, "avg_latency_ms": 22},
        "dns_test": {"resolved": True, "resolved_ip": "1.2.3.4", "dns_dhcp_enabled": True},
        "services": {"Spooler": {"status": "Running"}, "Dhcp": {"status": "Running"}, "Dnscache": {"status": "Running"}, "WlanSvc": {"status": "Running"}},
    }
    res_ok = run_offline_workflow(storage=temp_storage, telemetry_override=healthy, is_mock=True, force=True)
    assert res_ok["payload"]["decision_trace"]["decision_type"] == "HEALTH_CHECK"
    assert "no local rule failure" in res_ok["payload"]["decision_trace"]["why_explanation"].lower()

    sync_svc = EndpointSyncService(temp_storage, server_url="http://10.63.1.84:8000")
    reported = []
    with patch("diagnostics.EndpointDiagnostics.collect_all", return_value=healthy):
        with patch.object(sync_svc, "report_task_result", side_effect=lambda tid, payload: reported.append((tid, payload)) or True):
            with patch.object(agent_config, "mock_mode", True):
                execute_remote_task(
                    {"task_uuid": "task-remote-001", "tool_id": "renew_dhcp", "arguments": {}, "reason": "Dashboard test"},
                    temp_storage,
                    sync_svc,
                )
                execute_remote_task(
                    {"task_uuid": "task-remote-bad", "tool_id": "format_c_drive", "arguments": {}, "reason": "Blocked test"},
                    temp_storage,
                    sync_svc,
                )

    assert len(reported) == 2
    tid1, p1 = reported[0]
    assert tid1 == "task-remote-001"
    assert p1["status"] == "COMPLETED"
    assert "Dashboard test" in p1["why_explanation"]
    assert p1["telemetry"] == healthy

    tid2, p2 = reported[1]
    assert tid2 == "task-remote-bad"
    assert p2["result_status"] == "POLICY_REJECTED"
    assert "policy blocked" in p2["why_explanation"].lower()
