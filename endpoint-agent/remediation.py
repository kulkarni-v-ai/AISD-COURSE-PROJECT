import base64
import ctypes
import json
import logging
import os
import platform
import subprocess
import time
from typing import Dict, Any, List, Optional, Tuple
from agent_config import agent_config
from diagnostics import EndpointDiagnostics, _parse_netsh_dns_output

logger = logging.getLogger("aisd.agent.remediation")


def _is_admin() -> bool:
    if platform.system().lower() == "windows":
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin() != 0)
        except Exception:
            return False
    else:
        try:
            return os.geteuid() == 0
        except Exception:
            return False


def _ps_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _build_encoded_ps(inner_commands: str) -> str:
    wrapped = (
        "$ErrorActionPreference = 'Continue';\n"
        f"{inner_commands}\n"
        "if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { exit $LASTEXITCODE } else { exit 0 }"
    )
    return base64.b64encode(wrapped.encode("utf-16-le")).decode("ascii")


def _resolve_adapter(requested_name: Optional[str]) -> str:
    adapters = EndpointDiagnostics.get_all_adapters()
    req_clean = (requested_name or "").strip()
    if req_clean and req_clean.lower() not in {"auto", "default"}:
        for item in adapters:
            if item.get("name", "").lower() == req_clean.lower():
                return item["name"]
    primary = EndpointDiagnostics.get_adapter_status(adapters=adapters)
    return primary.get("name") or req_clean or "Wi-Fi"


def _run_elevated_powershell(inner_commands: str, timeout: float = 35.0) -> Tuple[int, str]:
    encoded_cmd = _build_encoded_ps(inner_commands)
    script = (
        f"$p = Start-Process -FilePath 'powershell.exe' "
        f"-ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand','{encoded_cmd}') "
        f"-Verb RunAs -WindowStyle Hidden -PassThru; "
        f"if ($p) {{ try {{ $null = $p.Handle }} catch {{}}; $p.WaitForExit(); exit ([int]$p.ExitCode) }} else {{ exit 1 }}"
    )
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if res.returncode == 0:
            return 0, "Elevated execution completed."
        msg = (res.stderr or res.stdout or f"Elevated execution returned exit code {res.returncode}.").strip()
        return res.returncode or 1, msg
    except subprocess.TimeoutExpired:
        return 1, f"Elevation prompt timed out after {int(timeout)}s."
    except Exception as exc:
        return 1, f"Elevation failed: {exc}"


class LocalRemediationPolicy:
    """Policy engine enforcing strict allowlist checks for offline remediation."""

    ALLOWLISTED_TOOLS: Dict[str, Dict[str, Any]] = {
        "enable_adapter": {
            "name": "Enable Network Adapter",
            "allowed_args": ["adapter_name"],
            "risk_level": "R2",
        },
        "renew_dhcp": {
            "name": "Renew DHCP Lease",
            "allowed_args": ["adapter_name"],
            "risk_level": "R2",
        },
        "flush_dns_cache": {
            "name": "Flush DNS Resolver Cache",
            "allowed_args": ["adapter_name"],
            "risk_level": "R1",
        },
        "restart_approved_service": {
            "name": "Restart Approved Service",
            "allowed_args": ["service_name"],
            "allowed_services": [
                "Spooler", "Dhcp", "Dnscache", "WlanSvc",
                "cups", "systemd-resolved", "NetworkManager", "ufw"
            ],
            "risk_level": "R2",
        },
    }

    @classmethod
    def is_tool_allowlisted(cls, tool_id: str) -> bool:
        return tool_id in cls.ALLOWLISTED_TOOLS

    @classmethod
    def check_policy(cls, tool_id: str, arguments: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
        """
        Validates whether a tool is approved for autonomous local endpoint execution.
        Returns: (is_allowed, reason)
        """
        arguments = arguments or {}
        if not cls.is_tool_allowlisted(tool_id):
            return False, f"Tool '{tool_id}' is not in the allowlist of approved local remediation actions."

        spec = cls.ALLOWLISTED_TOOLS[tool_id]
        if tool_id == "restart_approved_service":
            srv = arguments.get("service_name")
            if not srv:
                return False, "Missing required parameter 'service_name' for restart_approved_service."
            if srv not in spec["allowed_services"]:
                return False, f"Service '{srv}' is not approved for local restart. Approved services: {spec['allowed_services']}."

        return True, "Policy check passed."


class LocalRemediationExecutor:
    @staticmethod
    def execute(
        tool_id: str,
        arguments: Dict[str, Any],
        is_mock: bool = False,
        simulate_success: bool = True
    ) -> Tuple[bool, str, str]:
        """
        Executes allowlisted tool locally on the endpoint.
        Returns: (success, output, legacy_verification_status)
        """
        arguments = arguments or {}
        # Strict policy allowlist check before execution
        allowed, reason = LocalRemediationPolicy.check_policy(tool_id, arguments)
        if not allowed:
            logger.warning(f"Remediation policy rejection for {tool_id}: {reason}")
            return False, f"Policy check failed: {reason}", "NOT_RESOLVED"

        if is_mock:
            # Safe deterministic simulation
            if not simulate_success:
                return False, f"[MOCK ERROR] Remediation {tool_id} execution failed or timed out.", "NOT_RESOLVED"

            output = f"[MOCK ENDPOINT EXECUTION] Executed {tool_id} with {arguments}."
            if tool_id == "enable_adapter":
                output += f"\nEnabled Windows network adapter '{arguments.get('adapter_name', 'Wi-Fi')}'. Link state: Up."
                verification = "VERIFIED_RESOLVED"
            elif tool_id == "renew_dhcp":
                output += "\nReleasing Wi-Fi lease...\nRequesting new DHCP lease from campus AP...\nAssigned: 10.12.4.152, Gateway: 10.12.0.1."
                verification = "VERIFIED_RESOLVED"
            elif tool_id == "flush_dns_cache":
                output += "\nFlushed Windows DNS Resolver Cache."
                verification = "VERIFIED_RESOLVED"
            elif tool_id == "restart_approved_service":
                output += f"\nRestarted service {arguments.get('service_name')}."
                verification = "VERIFIED_RESOLVED"
            else:
                verification = "VERIFIED_RESOLVED"
            return True, output, verification

        # Linux Real Execution
        if platform.system().lower() == "linux":
            try:
                logs = []
                ok = False
                if tool_id == "enable_adapter":
                    adapter = arguments.get("adapter_name") or "eth0"
                    res = subprocess.run(["ip", "link", "set", adapter, "up"], capture_output=True, text=True, timeout=10)
                    logs.append(f"ip link set {adapter} up: exit {res.returncode}")
                    chk = subprocess.run(["ip", "link", "show", adapter], capture_output=True, text=True, timeout=5)
                    ok = "state UP" in chk.stdout or res.returncode == 0
                    output = "\n".join(logs)
                elif tool_id == "renew_dhcp":
                    adapter = arguments.get("adapter_name") or "eth0"
                    res = subprocess.run(["nmcli", "device", "reapply", adapter], capture_output=True, text=True, timeout=15)
                    if res.returncode != 0:
                        res = subprocess.run(["dhclient", "-r", adapter], capture_output=True, text=True, timeout=10)
                        res = subprocess.run(["dhclient", adapter], capture_output=True, text=True, timeout=15)
                    logs.append(f"Renew DHCP for {adapter}: exit {res.returncode}")
                    ok = res.returncode == 0
                    output = "\n".join(logs)
                elif tool_id == "flush_dns_cache":
                    res = subprocess.run(["resolvectl", "flush-caches"], capture_output=True, text=True, timeout=8)
                    if res.returncode != 0:
                        res = subprocess.run(["systemctl", "restart", "systemd-resolved"], capture_output=True, text=True, timeout=10)
                    logs.append(f"Flushed Linux DNS cache: exit {res.returncode}")
                    ok = res.returncode == 0
                    output = "\n".join(logs)
                elif tool_id == "restart_approved_service":
                    raw_srv = arguments.get("service_name", "")
                    service_map = {"Spooler": "cups", "Dhcp": "NetworkManager", "Dnscache": "systemd-resolved"}
                    native_srv = service_map.get(raw_srv, raw_srv)
                    res = subprocess.run(["systemctl", "restart", native_srv], capture_output=True, text=True, timeout=15)
                    logs.append(f"Restart service {native_srv}: exit {res.returncode}")
                    chk = subprocess.run(["systemctl", "is-active", native_srv], capture_output=True, text=True, timeout=5)
                    ok = chk.stdout.strip() == "active" or res.returncode == 0
                    output = "\n".join(logs)
                else:
                    return False, f"Tool '{tool_id}' not supported on Linux.", "INCONCLUSIVE"

                verification = "VERIFIED_RESOLVED" if ok else "NOT_RESOLVED"
                return ok, output[:1000], verification
            except Exception as e:
                return False, f"Linux remediation error: {e}", "VERIFICATION_ERROR"

        # Real Execution on Windows (Controlled allowlisted commands only)
        try:
            if tool_id == "enable_adapter":
                adapter = _resolve_adapter(arguments.get("adapter_name"))
                q_name = _ps_quote(adapter)
                cmd_str = f"Enable-NetAdapter -Name {q_name} -Confirm:$false"
                res = subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd_str],
                    capture_output=True, text=True, timeout=15
                )
                out = (res.stdout or res.stderr or "").strip()
                logs = [f"Target adapter: {adapter}"]
                if out:
                    logs.append(out)

                if res.returncode != 0 and ("access" in out.lower() or "denied" in out.lower() or "permission" in out.lower() or not _is_admin()):
                    elev_cmds = (
                        f"$iface = {q_name}; "
                        f"Enable-NetAdapter -Name $iface -Confirm:$false -ErrorAction SilentlyContinue; "
                        f"& netsh.exe interface set interface ('name=' + $iface) admin=enabled | Out-Null"
                    )
                    elev_code, elev_msg = _run_elevated_powershell(elev_cmds, timeout=35.0)
                    logs.append(f"Elevated Enable-NetAdapter (exit={elev_code}): {elev_msg}")

                # Poll adapter status briefly so Wi-Fi/Ethernet link negotiation can transition to Up
                status = "Unknown"
                for _ in range(6):
                    chk = subprocess.run(
                        ["powershell", "-NoProfile", "-Command", f"(Get-NetAdapter -Name {q_name} -ErrorAction SilentlyContinue).Status.ToString()"],
                        capture_output=True, text=True, timeout=6
                    )
                    status = (chk.stdout or "").strip() or "Unknown"
                    if status.lower() == "up":
                        break
                    time.sleep(1.0)

                logs.append(f"Adapter '{adapter}' status after enable: {status}")
                ok = status.lower() == "up"
                if not ok and status.lower() == "disabled" and not _is_admin():
                    logs.append(f"[ERROR] Adapter '{adapter}' remains Disabled. Administrator privileges required.")
                output = "\n".join(logs)

            elif tool_id == "renew_dhcp":
                adapter = _resolve_adapter(arguments.get("adapter_name"))
                pre_ip = EndpointDiagnostics.get_ip_configuration(adapter_name=adapter)
                logs = [
                    f"Target adapter: {adapter}",
                    f"Pre-remediation IPv4={pre_ip.get('ipv4_address')} Gateway={pre_ip.get('default_gateway')} DHCP={'Enabled' if pre_ip.get('dhcp_enabled') else 'Disabled'} StaticDNS={pre_ip.get('static_dns_configured')}",
                ]
                need_elev = False

                if pre_ip.get("dhcp_enabled") is False:
                    res_ip = subprocess.run(
                        ["netsh", "interface", "ipv4", "set", "address", f"name={adapter}", "source=dhcp"],
                        capture_output=True, text=True, timeout=15
                    )
                    out_ip = (res_ip.stdout + res_ip.stderr).strip()
                    if out_ip:
                        logs.append(f"netsh set address: {out_ip}")
                    if res_ip.returncode != 0 and "already enabled" not in out_ip.lower():
                        need_elev = True

                if pre_ip.get("static_dns_configured"):
                    res_dns = subprocess.run(
                        ["netsh", "interface", "ipv4", "set", "dnsservers", f"name={adapter}", "source=dhcp"],
                        capture_output=True, text=True, timeout=12
                    )
                    out_dns = (res_dns.stdout + res_dns.stderr).strip()
                    if out_dns:
                        logs.append(f"netsh set dnsservers: {out_dns}")
                    if res_dns.returncode != 0:
                        need_elev = True

                if need_elev and not _is_admin():
                    q_name = _ps_quote(adapter)
                    cmds = "\n".join([
                        f"$iface = {q_name}",
                        "& netsh.exe interface ipv4 set address ('name=' + $iface) source=dhcp | Out-Null",
                        "& netsh.exe interface ipv4 set dnsservers ('name=' + $iface) source=dhcp | Out-Null",
                        "& ipconfig.exe /renew $iface | Out-Null",
                    ])
                    elev_code, elev_msg = _run_elevated_powershell(cmds, timeout=35.0)
                    logs.append(f"Elevated UAC invocation (exit={elev_code}): {elev_msg}")
                else:
                    res_renew = subprocess.run(["ipconfig", "/renew", adapter], capture_output=True, text=True, timeout=20)
                    out_renew = (res_renew.stdout + res_renew.stderr).strip()
                    if out_renew:
                        logs.append(out_renew)
                    lower_renew = out_renew.lower()
                    if res_renew.returncode != 0 and ("requires elevation" in lower_renew or "administrator" in lower_renew or "access" in lower_renew) and not _is_admin():
                        q_name = _ps_quote(adapter)
                        elev_code, elev_msg = _run_elevated_powershell(
                            f"$iface = {q_name}; & ipconfig.exe /renew $iface | Out-Null",
                            timeout=30.0
                        )
                        logs.append(f"Elevated ipconfig /renew (exit={elev_code}): {elev_msg}")

                try:
                    ctypes.windll.dnsapi.DnsFlushResolverCache()
                except Exception:
                    pass

                # Allow DHCP lease + default gateway assignment to settle briefly before verifying
                post_ip = EndpointDiagnostics.get_ip_configuration(adapter_name=adapter)
                for _ in range(4):
                    if (post_ip.get("dhcp_enabled") is not False) and post_ip.get("has_valid_ip") and post_ip.get("default_gateway"):
                        break
                    time.sleep(1.0)
                    post_ip = EndpointDiagnostics.get_ip_configuration(adapter_name=adapter)

                logs.append(
                    f"Post-remediation IPv4={post_ip.get('ipv4_address')} Gateway={post_ip.get('default_gateway')} DHCP={'Enabled' if post_ip.get('dhcp_enabled') else 'Disabled'} StaticDNS={post_ip.get('static_dns_configured')}"
                )
                ok = (post_ip.get("dhcp_enabled") is not False) and bool(post_ip.get("has_valid_ip"))
                if post_ip.get("dhcp_enabled") is False:
                    logs.append(f"[ERROR] Adapter '{adapter}' still has DHCP disabled (Static IP). Administrator privileges required.")
                elif not post_ip.get("has_valid_ip"):
                    logs.append(f"[ERROR] Adapter '{adapter}' did not obtain a valid DHCP IPv4 address (got '{post_ip.get('ipv4_address')}').")
                output = "\n".join(logs)

            elif tool_id == "flush_dns_cache":
                adapter = _resolve_adapter(arguments.get("adapter_name"))
                dns_chk = subprocess.run(
                    ["netsh", "interface", "ipv4", "show", "dnsservers", f"name={adapter}"],
                    capture_output=True, text=True, timeout=6
                )
                pre_dns = _parse_netsh_dns_output(dns_chk.stdout + "\n" + dns_chk.stderr)
                logs = [f"Target adapter: {adapter}"]

                if pre_dns.get("static_dns_configured"):
                    res_dns = subprocess.run(
                        ["netsh", "interface", "ipv4", "set", "dnsservers", f"name={adapter}", "source=dhcp"],
                        capture_output=True, text=True, timeout=12
                    )
                    out_dns = (res_dns.stdout + res_dns.stderr).strip()
                    if out_dns:
                        logs.append(f"netsh set dnsservers source=dhcp: {out_dns}")
                    if res_dns.returncode != 0 and ("requires elevation" in out_dns.lower() or "administrator" in out_dns.lower() or not _is_admin()):
                        q_name = _ps_quote(adapter)
                        elev_code, elev_msg = _run_elevated_powershell(
                            f"$iface = {q_name}; & netsh.exe interface ipv4 set dnsservers ('name=' + $iface) source=dhcp | Out-Null",
                            timeout=30.0,
                        )
                        logs.append(f"Elevated UAC invocation (exit={elev_code}): {elev_msg}")

                flush_ok = False
                try:
                    res = ctypes.windll.dnsapi.DnsFlushResolverCache()
                    if res != 0:
                        logs.append("Flushed Windows DNS Client Cache via Win32 DnsFlushResolverCache API.")
                        flush_ok = True
                except Exception:
                    pass

                if not flush_ok:
                    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "Clear-DnsClientCache"]
                    res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                    logs.append((res.stdout + res.stderr).strip() or "Clear-DnsClientCache executed.")
                    flush_ok = (res.returncode == 0)

                if _is_admin():
                    try:
                        subprocess.run(["ipconfig", "/registerdns"], capture_output=True, text=True, timeout=10)
                    except Exception:
                        pass

                time.sleep(0.5)
                post_chk = subprocess.run(
                    ["netsh", "interface", "ipv4", "show", "dnsservers", f"name={adapter}"],
                    capture_output=True, text=True, timeout=6
                )
                post_dns = _parse_netsh_dns_output(post_chk.stdout + "\n" + post_chk.stderr)
                if post_dns.get("static_dns_configured"):
                    logs.append(f"[ERROR] Static DNS servers still configured on '{adapter}'. Administrator privileges required.")
                    ok = False
                else:
                    ok = flush_ok
                output = "\n".join(logs)

            elif tool_id == "restart_approved_service":
                srv = arguments.get("service_name")
                q_srv = _ps_quote(srv)
                cmd = ["powershell", "-NoProfile", "-Command", f"Restart-Service -Name {q_srv} -Force"]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
                logs = [f"Target service: {srv}"]
                out_srv = (res.stdout + res.stderr).strip()
                if out_srv:
                    logs.append(out_srv)
                if res.returncode != 0 and not _is_admin():
                    elev_code, elev_msg = _run_elevated_powershell(
                        f"Restart-Service -Name {q_srv} -Force -ErrorAction Stop",
                        timeout=30.0
                    )
                    logs.append(f"Elevated Restart-Service (exit={elev_code}): {elev_msg}")

                status = "Unknown"
                for _ in range(3):
                    chk = subprocess.run(
                        ["powershell", "-NoProfile", "-Command", f"(Get-Service -Name {q_srv} -ErrorAction SilentlyContinue).Status.ToString()"],
                        capture_output=True, text=True, timeout=6
                    )
                    status = chk.stdout.strip() or "Unknown"
                    if status.lower() == "running":
                        break
                    time.sleep(0.8)
                logs.append(f"Service '{srv}' status: {status}")
                ok = status.lower() == "running"
                output = "\n".join(logs)
            else:
                return False, f"Tool '{tool_id}' not executable directly on endpoint.", "INCONCLUSIVE"

            verification = "VERIFIED_RESOLVED" if ok else "NOT_RESOLVED"
            return ok, output[:1000], verification

        except Exception as e:
            return False, str(e), "VERIFICATION_ERROR"


class LocalVerifier:
    """Verifies whether a remediation action actually fixed the diagnosed issue."""

    @staticmethod
    def verify(
        rule_engine,
        initial_hypothesis_cause: str,
        fresh_evidence: Optional[Dict[str, Any]] = None,
        diagnostics_collector = None,
        is_mock: bool = True,
        simulate_outcome: Optional[str] = None,
        target_causes: Optional[List[str]] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Executes post-remediation verification by collecting fresh telemetry and re-running rules.
        Returns: (status, evidence_dict)
        Status values: 'resolved' | 'not_resolved' | 'verification_failed'
        """
        try:
            # Deterministic simulation overrides for testing
            if simulate_outcome in ["resolved", "not_resolved", "verification_failed"]:
                return simulate_outcome, {
                    "simulated": True,
                    "status": simulate_outcome,
                    "target_cause": initial_hypothesis_cause
                }

            # If mock mode without an explicit override, simulate a clean resolution
            if is_mock and fresh_evidence is None and diagnostics_collector is None:
                return "resolved", {
                    "simulated": True,
                    "status": "resolved",
                    "postcondition": "Simulated healthy network state: Valid IP (10.12.4.152), Gateway reachable, DNS working."
                }

            # Collect fresh diagnostics
            if fresh_evidence is None:
                if diagnostics_collector:
                    fresh_evidence = diagnostics_collector()
                else:
                    fresh_evidence = EndpointDiagnostics.collect_all()

            # Re-run rule engine on fresh evidence
            fresh_diagnosis = rule_engine.evaluate(fresh_evidence)

            # Check if any targeted remediated issue is still detected in hypotheses
            causes_to_check = target_causes or ([initial_hypothesis_cause] if initial_hypothesis_cause else [])
            still_present = False
            detected_causes = []
            for hyp in fresh_diagnosis.get("hypotheses", []):
                cause = hyp.get("cause", "")
                detected_causes.append(cause)
                for target in causes_to_check:
                    if cause == target or target in cause or cause in target:
                        still_present = True

            if fresh_diagnosis.get("status") == "insufficient_evidence" or not still_present:
                return "resolved", {
                    "fresh_diagnosis_status": fresh_diagnosis.get("status"),
                    "summary": "Original issue is no longer detected after remediation.",
                    "fresh_evidence": fresh_evidence
                }
            else:
                return "not_resolved", {
                    "fresh_diagnosis_status": fresh_diagnosis.get("status"),
                    "still_detected_causes": detected_causes,
                    "initial_issue": initial_hypothesis_cause,
                    "target_causes": causes_to_check,
                    "fresh_evidence": fresh_evidence
                }

        except Exception as e:
            logger.error(f"Error during verification: {e}")
            return "verification_failed", {"error": str(e)}
