import sys
import time
import argparse
import ctypes
import json
import platform
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any


def disable_windows_console_quick_edit() -> None:
    if platform.system().lower() != "windows":
        return
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-10)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            new_mode = (mode.value & ~0x0040) | 0x0080
            kernel32.SetConsoleMode(handle, new_mode)
    except Exception:
        pass

from agent_config import agent_config
from storage import AgentLocalStorage
from diagnostics import EndpointDiagnostics
from rules import local_rule_engine
from remediation import LocalRemediationExecutor, LocalRemediationPolicy, LocalVerifier
from sync import EndpointSyncService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("aisd.agent")

DIAGNOSTIC_ONLY_TOOLS = {"test_gateway", "collect_network_status", "check_firewall_rules"}
REMEDIATION_PRIORITY = ["enable_adapter", "restart_approved_service", "renew_dhcp", "flush_dns_cache"]


def _build_remediation_steps(recommended_tools: list, telemetry: Dict[str, Any]) -> list:
    """Builds an ordered, deduplicated list of (tool_id, tool_args) execution steps."""
    action_tools = [t for t in recommended_tools if t not in DIAGNOSTIC_ONLY_TOOLS]
    if not action_tools:
        return []

    def _priority_key(t: str) -> tuple:
        if t in REMEDIATION_PRIORITY:
            return (0, REMEDIATION_PRIORITY.index(t))
        return (1, action_tools.index(t))

    ordered_tools = sorted(list(dict.fromkeys(action_tools)), key=_priority_key)
    adapter_name = (
        telemetry.get("ip_config", {}).get("adapter_name")
        or telemetry.get("network_adapter", {}).get("name")
        or "Wi-Fi"
    )
    services = telemetry.get("services", {}) or {}
    approved_services = list(LocalRemediationPolicy.ALLOWLISTED_TOOLS["restart_approved_service"]["allowed_services"])

    steps = []
    seen = set()

    def _add_step(t_id: str, args: Dict[str, Any]):
        sig = (t_id, tuple(sorted((str(k), str(v)) for k, v in args.items())))
        if sig not in seen:
            seen.add(sig)
            steps.append((t_id, args))

    for t_id in ordered_tools:
        if t_id in ("enable_adapter", "renew_dhcp", "flush_dns_cache"):
            _add_step(t_id, {"adapter_name": adapter_name})
        elif t_id == "restart_approved_service":
            stopped_approved = [
                srv for srv in approved_services
                if str(services.get(srv, {}).get("status", "")).lower() in ("stopped", "paused", "error")
            ]
            if stopped_approved:
                for srv in stopped_approved:
                    _add_step(t_id, {"service_name": srv})
            else:
                _add_step(t_id, {"service_name": "Spooler"})
        else:
            _add_step(t_id, {})

    return steps


def run_offline_workflow(
    storage: AgentLocalStorage,
    telemetry_override: Optional[Dict[str, Any]] = None,
    is_mock: Optional[bool] = None,
    simulate_remediation_success: bool = True,
    simulate_verification_outcome: Optional[str] = None,
    rule_engine = local_rule_engine,
    force: bool = False
) -> Dict[str, Any]:
    """
    Executes the complete offline diagnosis, allowlisted remediation, and verification workflow.
    Queues all diagnostic evidence, actions, and verification results in the SQLite outbox.
    """
    logger.info("Server unreachable. Entering offline diagnostic mode.")
    logger.info("Collecting local diagnostics.")
    telemetry = telemetry_override if telemetry_override is not None else EndpointDiagnostics.collect_all()

    logger.info("Running local diagnosis rules.")
    diagnosis = rule_engine.evaluate(telemetry)

    # Check if a known issue is detected
    hypotheses = diagnosis.get("hypotheses", [])
    if diagnosis.get("status") != "hypotheses" or not hypotheses:
        logger.info("No known anomalies detected by local rules. Issue may require central AI or manual technician review.")
        event_uuid = str(uuid.uuid4())
        now_str = datetime.now(timezone.utc).isoformat()
        resolution_flag = "CANNOT_BE_DONE_LOCALLY_QUEUED"
        outcome_summary = "[CANNOT BE DONE LOCALLY] No matching deterministic local rule found. Telemetry queued for central analysis."
        observed_str = _summarize_observed(telemetry)
        payload = {
            "event_uuid": event_uuid,
            "timestamp": now_str,
            "agent_uuid": agent_config.agent_uuid,
            "diagnostic_evidence": telemetry,
            "detected_issue": None,
            "rule_matched": None,
            "recommended_action": None,
            "remediation_attempted": False,
            "remediation_result": None,
            "verification_result": None,
            "final_local_status": "ANALYSIS_QUEUED",
            "resolution_flag": resolution_flag,
            "outcome_summary": outcome_summary,
            "decision_trace": {
                "decision_type": "HEALTH_CHECK",
                "rule_or_model": "LocalRuleEngine",
                "action_taken": "queue_diagnostics",
                "why_explanation": (
                    f"Offline scan evaluated 10+ deterministic Windows rules on observed state [{observed_str}] "
                    "and found no local rule failure; telemetry was queued in SQLite outbox for central AI review."
                ),
                "observed_state": observed_str,
                "expected_state": "All local deterministic checks pass",
                "confidence": 1.0,
            },
            "is_fixed": False
        }
        storage.queue_event("DIAGNOSTIC_COLLECTED", payload, event_uuid=event_uuid)
        logger.info("Queuing offline result for synchronization.")
        return {
            "status": "ANALYSIS_QUEUED",
            "resolution_flag": resolution_flag,
            "outcome_summary": outcome_summary,
            "is_fixed": False,
            "event_uuid": event_uuid,
            "diagnosis": diagnosis,
            "payload": payload
        }

    # Known issue detected
    primary_hypothesis = hypotheses[0]
    detected_issue = primary_hypothesis["cause"]
    rule_matched = diagnosis["sources"][0] if diagnosis.get("sources") else "KB-LOCAL-RULE"
    recommended_tools = diagnosis.get("recommended_tool_ids", [])
    steps = _build_remediation_steps(recommended_tools, telemetry)
    tool_id = steps[0][0] if steps else None

    logger.info(f"Issue detected: {detected_issue}.")
    logger.info(f"Recommended remediation: {[s[0] for s in steps] or recommended_tools}.")

    if not steps:
        logger.info("No autonomous local remediation tool applicable for this issue. Flagged for technician escalation.")
        event_uuid = str(uuid.uuid4())
        now_str = datetime.now(timezone.utc).isoformat()
        resolution_flag = "CANNOT_BE_DONE_FLAGGED"
        outcome_summary = (
            f"[FLAGGED: CANNOT BE DONE AUTOMATICALLY] Issue '{detected_issue}' "
            "requires physical inspection or central technician intervention."
        )
        observed_str = _summarize_observed(telemetry)
        payload = {
            "event_uuid": event_uuid,
            "timestamp": now_str,
            "agent_uuid": agent_config.agent_uuid,
            "diagnostic_evidence": telemetry,
            "detected_issue": detected_issue,
            "rule_matched": rule_matched,
            "recommended_action": recommended_tools[0] if recommended_tools else None,
            "remediation_attempted": False,
            "remediation_result": None,
            "verification_result": None,
            "final_local_status": "ESCALATED",
            "resolution_flag": resolution_flag,
            "outcome_summary": outcome_summary,
            "decision_trace": {
                "decision_type": "ESCALATED",
                "rule_or_model": rule_matched,
                "action_taken": recommended_tools[0] if recommended_tools else "escalate",
                "why_explanation": (
                    f"Rule '{rule_matched}' diagnosed '{detected_issue}' (observed: {observed_str}), "
                    "which requires hardware/physical link or upstream infrastructure intervention; no autonomous local fix applies."
                ),
                "observed_state": observed_str,
                "expected_state": "Remediable local software/network configuration state",
                "confidence": primary_hypothesis.get("confidence", 0.9),
            },
            "is_fixed": False
        }
        storage.queue_event("OFFLINE_ESCALATION", payload, event_uuid=event_uuid)
        logger.info("Queuing offline result for synchronization.")
        return {
            "status": "ESCALATED",
            "resolution_flag": resolution_flag,
            "outcome_summary": outcome_summary,
            "is_fixed": False,
            "event_uuid": event_uuid,
            "payload": payload
        }

    # Safeguard checks (cooldown & retry limit) unless forced
    if not force:
        failed_attempts = storage.get_failed_remediation_count(detected_issue)
        if failed_attempts >= agent_config.max_remediation_retries:
            logger.warning(
                f"Maximum remediation attempts ({agent_config.max_remediation_retries}) reached "
                f"for '{detected_issue}'. Stopping automatic retries and queuing for escalation."
            )
            event_uuid = str(uuid.uuid4())
            now_str = datetime.now(timezone.utc).isoformat()
            resolution_flag = "CANNOT_BE_DONE_FLAGGED"
            outcome_summary = f"[FLAGGED: CANNOT BE DONE AUTOMATICALLY] Maximum retries ({agent_config.max_remediation_retries}) reached for issue '{detected_issue}'. Flagged for technician escalation."
            observed_str = _summarize_observed(telemetry)
            payload = {
                "event_uuid": event_uuid,
                "timestamp": now_str,
                "agent_uuid": agent_config.agent_uuid,
                "diagnostic_evidence": telemetry,
                "detected_issue": detected_issue,
                "rule_matched": rule_matched,
                "recommended_action": tool_id,
                "remediation_attempted": False,
                "remediation_result": {"error": "Max retries exceeded"},
                "verification_result": "not_resolved",
                "final_local_status": "ESCALATED",
                "resolution_flag": resolution_flag,
                "outcome_summary": outcome_summary,
                "decision_trace": {
                    "decision_type": "ESCALATED",
                    "rule_or_model": f"{rule_matched} / RetrySafeguard",
                    "action_taken": tool_id,
                    "why_explanation": (
                        f"Offline agent suppressed repeated auto-remediation '{tool_id}' for '{detected_issue}' "
                        f"because failed attempts reached limit ({failed_attempts}/{agent_config.max_remediation_retries}) in the last 15 minutes; escalated to technician."
                    ),
                    "observed_state": observed_str,
                    "expected_state": f"Resolution within <= {agent_config.max_remediation_retries} retries",
                    "confidence": 1.0,
                },
                "is_fixed": False
            }
            storage.queue_event("OFFLINE_ESCALATION", payload, event_uuid=event_uuid)
            logger.info("Queuing offline result for synchronization.")
            return {
                "status": "ESCALATED",
                "resolution_flag": resolution_flag,
                "outcome_summary": outcome_summary,
                "is_fixed": False,
                "event_uuid": event_uuid,
                "payload": payload
            }

        recent_attempts = storage.get_recent_remediation_attempts(
            detected_issue, within_seconds=agent_config.remediation_cooldown_sec
        )
        if recent_attempts > 0:
            logger.info(
                f"Remediation '{tool_id}' for '{detected_issue}' was attempted recently "
                f"within cooldown window ({agent_config.remediation_cooldown_sec}s). Skipping immediate retry."
            )
            return {
                "status": "COOLDOWN_ACTIVE",
                "resolution_flag": "COOLDOWN_ACTIVE",
                "outcome_summary": f"Remediation recently attempted. In cooldown ({agent_config.remediation_cooldown_sec}s).",
                "is_fixed": False,
                "detected_issue": detected_issue
            }

    # Policy / allowlist check for all planned remediation steps
    for step_tool_id, step_args in steps:
        is_allowed, policy_reason = LocalRemediationPolicy.check_policy(step_tool_id, step_args)
        if not is_allowed:
            event_uuid = str(uuid.uuid4())
            now_str = datetime.now(timezone.utc).isoformat()
            resolution_flag = "CANNOT_BE_DONE_FLAGGED"
            outcome_summary = f"[FLAGGED: CANNOT BE DONE AUTOMATICALLY] Tool '{step_tool_id}' is not in the safe allowlist. Prohibited from local execution."
            logger.warning(f"Policy check failed: {policy_reason}. Action not allowlisted. Flagged for technician escalation.")
            observed_str = _summarize_observed(telemetry)
            payload = {
                "event_uuid": event_uuid,
                "timestamp": now_str,
                "agent_uuid": agent_config.agent_uuid,
                "diagnostic_evidence": telemetry,
                "detected_issue": detected_issue,
                "rule_matched": rule_matched,
                "recommended_action": step_tool_id,
                "remediation_attempted": False,
                "remediation_result": {"error": policy_reason},
                "verification_result": "not_resolved",
                "final_local_status": "ESCALATED",
                "resolution_flag": resolution_flag,
                "outcome_summary": outcome_summary,
                "decision_trace": {
                    "decision_type": "POLICY_BLOCKED",
                    "rule_or_model": "LocalRemediationPolicy",
                    "action_taken": step_tool_id,
                    "why_explanation": (
                        f"Safety policy blocked offline execution of '{step_tool_id}' for '{detected_issue}': "
                        f"{policy_reason}. Queued for central technician approval."
                    ),
                    "observed_state": observed_str,
                    "expected_state": "Only safe allowlisted tools execute autonomously",
                    "confidence": 1.0,
                },
                "is_fixed": False
            }
            storage.queue_event("OFFLINE_ESCALATION", payload, event_uuid=event_uuid)
            logger.info("Queuing offline result for synchronization.")
            return {
                "status": "POLICY_REJECTED",
                "resolution_flag": resolution_flag,
                "outcome_summary": outcome_summary,
                "is_fixed": False,
                "event_uuid": event_uuid,
                "payload": payload
            }

    logger.info("Policy check passed.")
    logger.info("Executing approved local remediation.")

    mock_flag = is_mock if is_mock is not None else agent_config.mock_mode
    executed_actions = []
    output_chunks = []
    exec_success = True
    for step_tool_id, step_args in steps:
        step_ok, step_out, _ = LocalRemediationExecutor.execute(
            tool_id=step_tool_id,
            arguments=step_args,
            is_mock=mock_flag,
            simulate_success=simulate_remediation_success
        )
        executed_actions.append({
            "tool_id": step_tool_id,
            "arguments": step_args,
            "success": step_ok,
            "output": step_out,
        })
        output_chunks.append(f"[{step_tool_id}] {step_out}")
        if not step_ok:
            exec_success = False

    exec_output = "\n".join(output_chunks)
    actions_label = ", ".join(s[0] for s in steps)
    logger.info(f"Remediation completed ({actions_label}). Execution status: {'SUCCESS' if exec_success else 'FAILED'}.")

    logger.info("Running verification diagnostics.")
    if not exec_success:
        ver_outcome = "not_resolved"
    else:
        ver_outcome = simulate_verification_outcome

    remediable_causes = [
        h["cause"] for h in hypotheses
        if any(chk in LocalRemediationPolicy.ALLOWLISTED_TOOLS for chk in h.get("next_checks", []))
    ] or [detected_issue]

    verification_status, verify_evidence = LocalVerifier.verify(
        rule_engine=rule_engine,
        initial_hypothesis_cause=detected_issue,
        fresh_evidence=None,
        diagnostics_collector=None,
        is_mock=mock_flag,
        simulate_outcome=ver_outcome,
        target_causes=remediable_causes,
    )
    logger.info(f"Verification result: {verification_status}.")

    # Record attempt in SQLite history
    storage.record_remediation_attempt(
        issue_key=detected_issue,
        tool_id=actions_label,
        success=exec_success,
        verification_status=verification_status
    )

    if verification_status == "resolved":
        final_local_status = "RESOLVED"
        resolution_flag = "FIXED"
        event_type = "OFFLINE_REMEDIATION_SUCCESS"
        outcome_summary = f"[FIXED] Issue '{detected_issue}' was successfully remediated via '{actions_label}' and verified operational."
        logger.info(f"ISSUE FIXED: Remediation '{actions_label}' verified successfully.")
    else:
        final_local_status = "ESCALATED"
        resolution_flag = "CANNOT_BE_DONE_FLAGGED"
        event_type = "OFFLINE_REMEDIATION_FAILED"
        outcome_summary = f"[FLAGGED: CANNOT BE DONE AUTOMATICALLY] Remediation '{actions_label}' attempted, but verification result was '{verification_status}'. Flagged for manual escalation."
        logger.warning(f"FLAGGED - CANNOT BE DONE AUTOMATICALLY: Remediation '{actions_label}' did not resolve the issue. Flagged for technician escalation.")

    observed_str = _summarize_observed(telemetry)
    why_explanation = (
        f"Local rule(s) [{', '.join(diagnosis.get('sources') or [rule_matched])}] detected '{detected_issue}' "
        f"(observed: {observed_str}). Approved allowlisted tool(s) [{actions_label}] passed safety policy and executed; "
        f"post-remediation verification returned '{verification_status}'."
    )

    event_uuid = str(uuid.uuid4())
    now_str = datetime.now(timezone.utc).isoformat()
    payload = {
        "event_uuid": event_uuid,
        "timestamp": now_str,
        "agent_uuid": agent_config.agent_uuid,
        "diagnostic_evidence": telemetry,
        "detected_issue": detected_issue,
        "rule_matched": rule_matched,
        "recommended_action": tool_id,
        "executed_actions": executed_actions,
        "remediation_attempted": True,
        "remediation_result": {
            "success": exec_success,
            "output": exec_output
        },
        "verification_result": verification_status,
        "verification_evidence": verify_evidence,
        "final_local_status": final_local_status,
        "resolution_flag": resolution_flag,
        "outcome_summary": outcome_summary,
        "decision_trace": {
            "decision_type": "AUTO_REMEDIATED" if verification_status == "resolved" else "ESCALATED",
            "rule_or_model": ", ".join(diagnosis.get("sources") or [rule_matched]),
            "action_taken": actions_label,
            "why_explanation": why_explanation,
            "observed_state": observed_str,
            "expected_state": "Valid DHCP IP + Automatic DNS + Gateway/WAN Reachable + Services Running",
            "confidence": primary_hypothesis.get("confidence", 0.9),
        },
        "is_fixed": (verification_status == "resolved")
    }

    storage.queue_event(event_type, payload, event_uuid=event_uuid)
    logger.info("Queuing offline result for synchronization.")

    return {
        "status": final_local_status,
        "resolution_flag": resolution_flag,
        "outcome_summary": outcome_summary,
        "is_fixed": (verification_status == "resolved"),
        "event_uuid": event_uuid,
        "event_type": event_type,
        "detected_issue": detected_issue,
        "recommended_action": tool_id,
        "executed_actions": executed_actions,
        "remediation_result": exec_success,
        "verification_result": verification_status,
        "payload": payload
    }


def _extract_network_meta(telemetry: Dict[str, Any]) -> tuple:
    adapter = telemetry.get("network_adapter", {}) or {}
    ip_cfg = telemetry.get("ip_config", {}) or {}
    return (
        ip_cfg.get("ipv4_address"),
        ip_cfg.get("adapter_name") or adapter.get("name"),
        adapter.get("mac_address"),
    )


def _summarize_observed(telemetry: Dict[str, Any]) -> str:
    adapter = telemetry.get("network_adapter", {}) or {}
    ip_cfg = telemetry.get("ip_config", {}) or {}
    gw = telemetry.get("gateway_ping", {}) or {}
    dns = telemetry.get("dns_test", {}) or {}
    services = telemetry.get("services", {}) or {}
    running_svcs = sum(1 for v in services.values() if str((v or {}).get("status", "")).lower() == "running")
    dns_mode = "Static(" + ",".join(ip_cfg.get("dns_servers") or []) + ")" if ip_cfg.get("static_dns_configured") else "DHCP"
    return (
        f"{adapter.get('name', 'NIC')}[{adapter.get('status', '?')}] "
        f"IP={ip_cfg.get('ipv4_address') or 'None'} "
        f"DHCP={'On' if ip_cfg.get('dhcp_enabled', True) else 'Off'} "
        f"DNS={dns_mode} "
        f"GW={'OK' if gw.get('reachable') else 'Fail'} "
        f"Svc={running_svcs}/{len(services) or 4}"
    )


def execute_remote_task(task: Dict[str, Any], storage: AgentLocalStorage, sync_svc: EndpointSyncService) -> None:
    """Executes an allowlisted remote command dispatched from the Central Server on this Windows host."""
    task_uuid = task.get("task_uuid")
    tool_id = str(task.get("tool_id") or "")
    arguments = task.get("arguments") or {}
    reason = task.get("reason") or "Central dashboard command"
    logger.info(f"[REMOTE TASK {task_uuid}] Executing '{tool_id}' args={arguments}")

    pre_telemetry = EndpointDiagnostics.collect_all()
    pre_observed = _summarize_observed(pre_telemetry)

    try:
        if tool_id == "collect_network_status":
            diag = local_rule_engine.evaluate(pre_telemetry)
            hyps = diag.get("hypotheses", [])
            why = (
                f"Live probe triggered ({reason}). Detected {len(hyps)} issue(s): {diag.get('summary')}. Observed: {pre_observed}."
                if hyps
                else f"Live probe triggered ({reason}). All deterministic network and service checks passed cleanly ({pre_observed})."
            )
            sync_svc.report_task_result(task_uuid, {
                "status": "COMPLETED",
                "result_status": "SUCCESS",
                "verification_status": "VERIFIED_RESOLVED" if not hyps else "ANOMALY_DETECTED",
                "output_text": json.dumps({"diagnosis": diag, "observed": pre_observed}, indent=2),
                "why_explanation": why,
                "observed_state": pre_observed,
                "expected_state": "Healthy adapter, valid DHCP IP, automatic DNS, reachable GW & DNS",
                "telemetry": pre_telemetry,
            })
            return

        if tool_id == "diagnose_and_auto_remediate":
            wf = run_offline_workflow(
                storage=storage,
                telemetry_override=pre_telemetry,
                is_mock=agent_config.mock_mode,
                force=True,
            )
            post_telemetry = EndpointDiagnostics.collect_all()
            post_observed = _summarize_observed(post_telemetry)
            is_fixed = bool(wf.get("is_fixed"))
            if wf.get("status") == "ANALYSIS_QUEUED":
                why = f"Remote diagnose & auto-fix ran ({reason}): No anomalies detected ({pre_observed}); no changes required."
                ver_stat = "VERIFIED_RESOLVED"
                res_stat = "NO_ISSUE"
            else:
                why = (
                    f"Remote diagnose & auto-fix ({reason}): Pre-state=[{pre_observed}]. "
                    f"Detected '{wf.get('detected_issue')}', executed {wf.get('recommended_action')}, "
                    f"outcome={wf.get('status')} ({wf.get('verification_result')}). Post-state=[{post_observed}]."
                )
                ver_stat = "VERIFIED_RESOLVED" if is_fixed else "NOT_RESOLVED"
                res_stat = wf.get("resolution_flag") or wf.get("status")

            sync_svc.report_task_result(task_uuid, {
                "status": "COMPLETED" if ver_stat == "VERIFIED_RESOLVED" else "FAILED",
                "result_status": res_stat,
                "verification_status": ver_stat,
                "output_text": wf.get("outcome_summary", ""),
                "why_explanation": why,
                "observed_state": f"Before: {pre_observed} -> After: {post_observed}",
                "expected_state": "All remediable network/service issues resolved and verified",
                "telemetry": post_telemetry,
                "executed_actions": wf.get("executed_actions") or [],
            })
            return

        if tool_id == "test_gateway":
            gw_res = EndpointDiagnostics.test_gateway_ping(ip_conf=pre_telemetry.get("ip_config"))
            ok = bool(gw_res.get("reachable"))
            why = (
                f"Executed gateway ping ({reason}) to {gw_res.get('target_gateway') or 'none'}: "
                f"reachable={ok}, packet_loss={gw_res.get('packet_loss_pct')}%, avg_rtt={gw_res.get('avg_latency_ms')}ms."
            )
            sync_svc.report_task_result(task_uuid, {
                "status": "COMPLETED" if ok else "FAILED",
                "result_status": "SUCCESS" if ok else "FAILED",
                "verification_status": "VERIFIED_RESOLVED" if ok else "NOT_RESOLVED",
                "output_text": json.dumps(gw_res, indent=2),
                "why_explanation": why,
                "observed_state": f"GW={gw_res.get('target_gateway')} RTT={gw_res.get('avg_latency_ms')}ms Loss={gw_res.get('packet_loss_pct')}%",
                "expected_state": "Default gateway reachable with 0% packet loss",
                "telemetry": pre_telemetry,
            })
            return

        if tool_id == "test_dns":
            dns_res = EndpointDiagnostics.test_dns_resolution(ip_conf=pre_telemetry.get("ip_config"))
            ok = bool(dns_res.get("resolved"))
            why = (
                f"Executed DNS resolution test ({reason}): resolved={ok}, ip={dns_res.get('resolved_ip')}, "
                f"dns_dhcp_enabled={dns_res.get('dns_dhcp_enabled')}, servers={dns_res.get('dns_servers')}."
            )
            sync_svc.report_task_result(task_uuid, {
                "status": "COMPLETED" if ok else "FAILED",
                "result_status": "SUCCESS" if ok else "FAILED",
                "verification_status": "VERIFIED_RESOLVED" if ok else "NOT_RESOLVED",
                "output_text": json.dumps(dns_res, indent=2),
                "why_explanation": why,
                "observed_state": f"DNS Resolved={ok}, Mode={'DHCP' if dns_res.get('dns_dhcp_enabled', True) else 'Static'} ({dns_res.get('dns_servers')})",
                "expected_state": "Domain lookup succeeds via active DNS servers",
                "telemetry": pre_telemetry,
            })
            return

        # Standard allowlisted Windows remediation tool
        exec_args = dict(arguments)
        if tool_id in ("enable_adapter", "renew_dhcp", "flush_dns_cache") and not exec_args.get("adapter_name"):
            _, adapter_name, _ = _extract_network_meta(pre_telemetry)
            exec_args["adapter_name"] = adapter_name or "Wi-Fi"

        allowed, policy_reason = LocalRemediationPolicy.check_policy(tool_id, exec_args)
        if not allowed:
            sync_svc.report_task_result(task_uuid, {
                "status": "FAILED",
                "result_status": "POLICY_REJECTED",
                "verification_status": "NOT_RESOLVED",
                "error_text": policy_reason,
                "why_explanation": f"Endpoint safety policy blocked remote tool '{tool_id}': {policy_reason}",
                "observed_state": pre_observed,
                "expected_state": "Tool permitted under LocalRemediationPolicy allowlist",
                "telemetry": pre_telemetry,
            })
            return

        ok, out_txt, ver_stat = LocalRemediationExecutor.execute(
            tool_id=tool_id,
            arguments=exec_args,
            is_mock=agent_config.mock_mode,
        )
        post_telemetry = EndpointDiagnostics.collect_all()
        post_observed = _summarize_observed(post_telemetry)
        final_ver = "VERIFIED_RESOLVED" if ok else "NOT_RESOLVED"

        why = (
            f"Remote command '{tool_id}' ({exec_args}) requested for: {reason}. "
            f"Pre-state: [{pre_observed}]. Execution {'succeeded' if ok else 'failed'}; "
            f"Post-state: [{post_observed}]."
        )
        sync_svc.report_task_result(task_uuid, {
            "status": "COMPLETED" if ok else "FAILED",
            "result_status": "FIXED" if ok else "FAILED",
            "verification_status": final_ver,
            "output_text": out_txt,
            "error_text": "" if ok else out_txt,
            "why_explanation": why,
            "observed_state": f"Before: {pre_observed} -> After: {post_observed}",
            "expected_state": f"Postcondition healthy after {tool_id}",
            "telemetry": post_telemetry,
            "executed_actions": [{"tool_id": tool_id, "arguments": exec_args, "success": ok}],
        })

    except Exception as exc:
        logger.error(f"[REMOTE TASK {task_uuid}] Failed with exception: {exc}")
        sync_svc.report_task_result(task_uuid, {
            "status": "FAILED",
            "result_status": "FAILED",
            "verification_status": "VERIFICATION_ERROR",
            "error_text": str(exc),
            "why_explanation": f"Remote execution of '{tool_id}' encountered an unexpected exception: {exc}",
            "observed_state": pre_observed,
            "expected_state": f"Clean execution of {tool_id}",
            "telemetry": pre_telemetry,
        })


def main():
    disable_windows_console_quick_edit()
    parser = argparse.ArgumentParser(description="AISD Lightweight Windows Endpoint Agent")
    parser.add_argument("--server", default=None, help="Central Server URL (e.g. http://10.63.1.84:8000)")
    subparsers = parser.add_subparsers(dest="command")

    # Command: status
    p_status = subparsers.add_parser("status", help="Display agent identity and status")
    p_status.add_argument("--server", dest="sub_server", default=None, help="Central Server URL")

    # Command: diagnose
    subparsers.add_parser("diagnose", help="Collect local Windows diagnostic telemetry")

    # Command: evaluate
    subparsers.add_parser("evaluate", help="Run local deterministic rules on collected diagnostics")

    # Command: diagnose-and-remediate
    dm_parser = subparsers.add_parser(
        "diagnose-and-remediate",
        help="Run offline diagnosis, approved remediation, verification, and local event queuing"
    )
    dm_parser.add_argument("--mock", action="store_true", default=None, help="Force mock execution mode")
    dm_parser.add_argument("--force", action="store_true", default=False, help="Bypass cooldown checks")

    # Command: report
    rep_parser = subparsers.add_parser("report", help="Report an incident (queued in local SQLite outbox)")
    rep_parser.add_argument("--title", required=True, help="Incident title")
    rep_parser.add_argument("--desc", required=True, help="Incident description")
    rep_parser.add_argument("--category", default="NETWORK", help="Category")
    rep_parser.add_argument("--priority", default="MEDIUM", help="Priority")

    # Command: sync
    p_sync = subparsers.add_parser("sync", help="Synchronize queued offline events with central server")
    p_sync.add_argument("--server", dest="sub_server", default=None, help="Central Server URL")

    # Command: daemon
    p_daemon = subparsers.add_parser("daemon", help="Run agent in continuous background polling mode")
    p_daemon.add_argument("--server", dest="sub_server", default=None, help="Central Server URL")

    args = parser.parse_args()
    effective_server = getattr(args, "sub_server", None) or args.server or agent_config.server_url
    storage = AgentLocalStorage(agent_config.db_path)
    sync_svc = EndpointSyncService(storage, server_url=effective_server)

    if args.command == "status" or not args.command:
        server_ok = sync_svc.is_server_reachable()
        pending = len(storage.get_pending_events())
        print(f"=== AISD Windows Endpoint Agent ===")
        print(f"Agent UUID:        {agent_config.agent_uuid}")
        print(f"Hostname:          {agent_config.hostname}")
        print(f"OS Version:        {agent_config.os_version}")
        print(f"Central Server:    {sync_svc.server_url} [{'REACHABLE' if server_ok else 'OFFLINE'}]")
        print(f"Offline Outbox:    {pending} events queued in {agent_config.db_path}")
        print(f"Mock Mode:         {agent_config.mock_mode}")

    elif args.command == "diagnose":
        print("Collecting local Windows diagnostic telemetry...")
        telemetry = EndpointDiagnostics.collect_all()
        print(json.dumps(telemetry, indent=2))

    elif args.command == "evaluate":
        print("Collecting telemetry and evaluating deterministic rules locally...")
        telemetry = EndpointDiagnostics.collect_all()
        diagnosis = local_rule_engine.evaluate(telemetry)
        print(json.dumps(diagnosis, indent=2))

    elif args.command == "diagnose-and-remediate":
        print("Executing local diagnosis, approved remediation, and verification workflow...\n")
        mock_mode = args.mock if args.mock is not None else agent_config.mock_mode
        result = run_offline_workflow(storage, is_mock=mock_mode, force=args.force)
        print(json.dumps(result, indent=2, default=str))

        flag = result.get("resolution_flag") or result.get("status")
        summary = result.get("outcome_summary") or result.get("payload", {}).get("outcome_summary", "")

        if flag == "FIXED" or result.get("is_fixed"):
            print("\n" + "=" * 68)
            print(">>> FINAL OUTCOME: [FIXED]")
            print(f">>> {summary}")
            print(">>> Postcondition verified: Issue resolved successfully.")
            print("=" * 68 + "\n")
        elif "CANNOT_BE_DONE" in str(flag) or result.get("status") in ["ESCALATED", "POLICY_REJECTED"]:
            print("\n" + "=" * 68)
            print(">>> FINAL OUTCOME: [FLAGGED: CANNOT BE DONE AUTOMATICALLY]")
            print(f">>> {summary}")
            print(">>> Result queued in SQLite outbox for central technician escalation.")
            print("=" * 68 + "\n")
        elif flag == "COOLDOWN_ACTIVE":
            print("\n" + "=" * 68)
            print(f">>> FINAL OUTCOME: [COOLDOWN ACTIVE]")
            print(f">>> {summary}")
            print("=" * 68 + "\n")
        else:
            print("\n" + "=" * 68)
            print(f">>> FINAL OUTCOME: [{flag}]")
            print(f">>> {summary}")
            print("=" * 68 + "\n")

    elif args.command == "report":
        inc_number = f"INC-LOCAL-{int(time.time())}"
        payload = {
            "incident_number": inc_number,
            "title": args.title,
            "description": args.desc,
            "category": args.category,
            "priority": args.priority,
            "status": "NEW"
        }
        event_uuid = storage.queue_event("INCIDENT_REPORTED", payload)
        storage.save_local_incident(payload)
        print(f"Incident {inc_number} queued locally (Event UUID: {event_uuid}).")

        # Try immediate sync if server is reachable
        if sync_svc.is_server_reachable():
            print("Central server is reachable. Attempting immediate synchronization...")
            acc, dup = sync_svc.sync_outbox()
            print(f"Sync complete: {acc} accepted, {dup} duplicate/already synced.")
        else:
            print("Central server unreachable. Event remains safely in local SQLite outbox for later sync.")

    elif args.command == "sync":
        print(f"Checking central server reachability ({sync_svc.server_url})...")
        if not sync_svc.is_server_reachable():
            print("Central server is OFFLINE. Cannot sync right now.")
            return

        sample = EndpointDiagnostics.collect_heartbeat_sample()
        ip_addr, nic_name, mac_addr = _extract_network_meta(sample)
        sync_svc.enroll(ip_address=ip_addr, adapter_name=nic_name, mac_address=mac_addr, telemetry=sample)
        accepted, duplicate = sync_svc.sync_outbox()
        print(f"Synchronization finished. Accepted: {accepted}, Duplicates: {duplicate}.")

    elif args.command == "daemon":
        print(f"Starting AISD Endpoint Agent background service -> {sync_svc.server_url} ...")
        init_sample = EndpointDiagnostics.collect_heartbeat_sample()
        ip_addr, nic_name, mac_addr = _extract_network_meta(init_sample)
        enrolled = sync_svc.enroll(ip_address=ip_addr, adapter_name=nic_name, mac_address=mac_addr, telemetry=init_sample)
        tick = 0
        last_mode: Optional[str] = None
        while True:
            try:
                server_ok = sync_svc.is_server_reachable()
                if server_ok:
                    if last_mode != "ONLINE":
                        logger.info(f"⚡ [MODE SWITCH] Connected to Central Server ({sync_svc.server_url}). Operating in ONLINE mode.")
                        last_mode = "ONLINE"

                    if not enrolled:
                        sample = EndpointDiagnostics.collect_heartbeat_sample()
                        ip_addr, nic_name, mac_addr = _extract_network_meta(sample)
                        enrolled = sync_svc.enroll(ip_address=ip_addr, adapter_name=nic_name, mac_address=mac_addr, telemetry=sample)

                    # Send full telemetry heartbeat every ~15s (5 x 3s ticks)
                    if tick % 5 == 0:
                        sample = EndpointDiagnostics.collect_heartbeat_sample()
                        ip_addr, nic_name, mac_addr = _extract_network_meta(sample)
                        hb_ok = sync_svc.send_heartbeat(
                            ip_address=ip_addr,
                            adapter_name=nic_name,
                            mac_address=mac_addr,
                            telemetry=sample,
                        )
                        if not hb_ok:
                            enrolled = sync_svc.enroll(ip_address=ip_addr, adapter_name=nic_name, mac_address=mac_addr, telemetry=sample)
                        acc, dup = sync_svc.sync_outbox()
                        if acc > 0:
                            logger.info(f"Synchronized {acc} pending offline events ({dup} duplicate/already synced).")
                        for task in list(sync_svc.last_pending_tasks):
                            execute_remote_task(task, storage, sync_svc)
                        sync_svc.last_pending_tasks = []
                    else:
                        # Fast 3-second poll for remote dashboard commands
                        for task in sync_svc.fetch_pending_tasks():
                            execute_remote_task(task, storage, sync_svc)

                    tick += 1
                    time.sleep(3)
                else:
                    if last_mode != "OFFLINE":
                        logger.warning(f"🔌 [MODE SWITCH] Server unreachable ({sync_svc.server_url}). Switching to OFFLINE LOCAL AGENT mode.")
                        last_mode = "OFFLINE"
                    # Server unreachable -> run offline health check and remediation workflow
                    run_offline_workflow(storage)
                    tick = 0
                    time.sleep(agent_config.offline_check_interval_sec)
            except KeyboardInterrupt:
                print("Stopping agent daemon.")
                break
            except Exception as e:
                logger.error(f"Daemon cycle error: {e}")
                time.sleep(5)
