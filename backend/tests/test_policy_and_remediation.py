import pytest
from app.remediation.registry import get_tool, is_tool_registered
from app.remediation.policy import policy_engine
from app.remediation.executor import remediation_executor


def test_registered_tools():
    assert is_tool_registered("renew_dhcp")
    assert is_tool_registered("test_gateway")
    assert is_tool_registered("flush_dns_cache")
    assert is_tool_registered("restart_approved_service")
    assert not is_tool_registered("arbitrary_bash_command; rm -rf /")


def test_policy_blocks_unregistered_tools():
    allowed, reason, _, _ = policy_engine.evaluate_plan_creation(
        tool_id="format_c_drive",
        arguments={},
        user_role="admin"
    )
    assert allowed is False
    assert "not in the predefined allowed tool registry" in reason


def test_policy_flags_approval_required_for_r2():
    allowed, reason, tool, approval_req = policy_engine.evaluate_plan_creation(
        tool_id="renew_dhcp",
        arguments={"adapter_name": "Wi-Fi"},
        user_role="technician"
    )
    assert allowed is True
    assert tool.risk_level == "R2"
    assert approval_req is True


def test_policy_blocks_execution_without_approval():
    can_exec, reason = policy_engine.can_execute(
        tool_id="renew_dhcp",
        approval_status="PENDING",
        approval_required=True,
        user_role="technician"
    )
    assert can_exec is False
    assert "requires technician approval" in reason


def test_policy_allows_execution_when_approved():
    can_exec, reason = policy_engine.can_execute(
        tool_id="renew_dhcp",
        approval_status="APPROVED",
        approval_required=True,
        user_role="technician"
    )
    assert can_exec is True


@pytest.mark.asyncio
async def test_mock_executor_and_verifier_success():
    status, exit_code, out, err, v_status, v_evidence = await remediation_executor.execute(
        tool_id="renew_dhcp",
        arguments={"adapter_name": "Wi-Fi"},
        is_mock=True,
        simulate_outcome="VERIFIED_RESOLVED"
    )
    assert status == "SUCCESS"
    assert exit_code == 0
    assert "MOCK EXECUTION" in out
    assert v_status == "VERIFIED_RESOLVED"
    assert v_evidence.get("ip_address") == "10.12.4.152"


@pytest.mark.asyncio
async def test_mock_executor_verification_failure():
    status, exit_code, out, err, v_status, v_evidence = await remediation_executor.execute(
        tool_id="renew_dhcp",
        arguments={"adapter_name": "Wi-Fi"},
        is_mock=True,
        simulate_outcome="NOT_RESOLVED"
    )
    assert status == "SUCCESS"
    assert v_status == "NOT_RESOLVED"
    assert "Failure" in v_evidence.get("result", "")
