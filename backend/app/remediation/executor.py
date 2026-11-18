import asyncio
import json
import logging
from typing import Dict, Any, Tuple, Optional
from app.core.config import settings
from app.remediation.registry import get_tool
from app.remediation.verifier import verification_engine
from app.remediation import windows_net

logger = logging.getLogger("aisd.remediation")


class RemediationExecutor:
    def __init__(self):
        self.default_mock = settings.REMEDIATION_MOCK_MODE

    async def execute(
        self,
        tool_id: str,
        arguments: Dict[str, Any],
        is_mock: Optional[bool] = None,
        simulate_outcome: str = "VERIFIED_RESOLVED"
    ) -> Tuple[str, Optional[int], str, str, str, Dict[str, Any]]:
        """
        Executes a predefined remediation tool and runs postcondition verification.
        Returns:
            (execution_status, exit_code, output_redacted, error_redacted, verification_status, verification_evidence)
        """
        tool = get_tool(tool_id)
        if not tool:
            return "FAILED", 1, "", f"Tool '{tool_id}' is not registered.", "NOT_RESOLVED", {}

        arguments = arguments or {}
        use_mock = self.default_mock if is_mock is None else is_mock

        if use_mock:
            # Deterministic simulated execution
            output = f"[MOCK EXECUTION] Successfully executed tool '{tool_id}' with arguments: {arguments}"
            if tool_id == "renew_dhcp":
                output += "\nReleasing adapter lease...\nNegotiating DHCP with campus controller...\nAssigned 10.12.4.152, Gateway 10.12.0.1, DNS 10.12.0.5."
            elif tool_id == "flush_dns_cache":
                output += "\nSuccessfully flushed the DNS Resolver Cache."
            elif tool_id == "restart_approved_service":
                output += f"\nStopping service {arguments.get('service_name')}...\nStarting service {arguments.get('service_name')}... State: RUNNING."

            # Postcondition verification
            v_status, v_evidence = await verification_engine.verify(
                tool_id=tool_id,
                verification_type=tool.verification_type,
                arguments=arguments,
                is_mock=True,
                simulate_outcome=simulate_outcome
            )

            return "SUCCESS", 0, output, "", v_status, v_evidence

        # Real Execution on Windows (Controlled allowlisted commands only)
        try:
            out_str = ""
            err_str = ""
            exit_code = 0
            exec_args = dict(arguments)

            if tool_id == "flush_dns_cache":
                res = await asyncio.to_thread(windows_net.reset_dns_to_dhcp_and_flush, exec_args.get("adapter_name"))
                out_str = res.get("output", "")
                err_str = res.get("error", "")
                exit_code = int(res.get("exit_code", 0 if res.get("success") else 1))
                if res.get("adapter_name"):
                    exec_args["adapter_name"] = res["adapter_name"]

            elif tool_id == "renew_dhcp":
                res = await asyncio.to_thread(windows_net.renew_dhcp_for_adapter, exec_args.get("adapter_name"))
                out_str = res.get("output", "")
                err_str = res.get("error", "")
                exit_code = int(res.get("exit_code", 0 if res.get("success") else 1))
                if res.get("adapter_name"):
                    exec_args["adapter_name"] = res["adapter_name"]

            elif tool_id == "test_gateway":
                def _run_gw():
                    adapter = windows_net.resolve_active_adapter(exec_args.get("adapter_name"))
                    gw = exec_args.get("gateway_ip")
                    if not gw:
                        ip_cfg = windows_net.get_ip_config_for_adapter(adapter)
                        gw = ip_cfg.get("default_gateway")
                    count = int(exec_args.get("count", 4))
                    if not gw:
                        return {"success": False, "output": "", "error": f"No default gateway configured on adapter '{adapter}'.", "adapter": adapter}
                    ping_res = windows_net.ping_host(gw, count=count, timeout_ms=1500)
                    return {
                        "success": bool(ping_res.get("reachable")),
                        "output": ping_res.get("raw_output") or f"Ping {gw}: packet_loss={ping_res.get('packet_loss_pct')}%",
                        "error": "" if ping_res.get("reachable") else f"Default gateway {gw} unreachable ({ping_res.get('packet_loss_pct', 100)}% loss).",
                        "gateway_ip": gw,
                        "adapter": adapter,
                    }

                res = await asyncio.to_thread(_run_gw)
                out_str = res["output"]
                err_str = res["error"]
                exit_code = 0 if res["success"] else 1
                if res.get("gateway_ip"):
                    exec_args["gateway_ip"] = res["gateway_ip"]
                if res.get("adapter"):
                    exec_args["adapter_name"] = res["adapter"]

            elif tool_id == "test_dns":
                domains = exec_args.get("domains") or ["college.edu", "google.com"]
                adapter = await asyncio.to_thread(windows_net.resolve_active_adapter, exec_args.get("adapter_name"))
                dns_res = await asyncio.to_thread(windows_net.test_dns_hosts, domains, adapter)
                out_str = json.dumps(dns_res, indent=2)
                exit_code = 0 if dns_res.get("resolved") else 1
                if exit_code != 0:
                    err_str = "DNS resolution failed for tested domains."
                if adapter:
                    exec_args["adapter_name"] = adapter

            elif tool_id == "enable_adapter":
                res = await asyncio.to_thread(windows_net.enable_network_adapter, exec_args.get("adapter_name"))
                out_str = res.get("output", "")
                err_str = res.get("error", "")
                exit_code = int(res.get("exit_code", 0 if res.get("success") else 1))
                if res.get("adapter_name"):
                    exec_args["adapter_name"] = res["adapter_name"]

            elif tool_id == "restart_approved_service":
                srv = exec_args.get("service_name")
                if srv not in ["Spooler", "Dhcp", "Dnscache"]:
                    return "FAILED", 1, "", f"Service '{srv}' is not in approved restart allowlist.", "NOT_RESOLVED", {}
                res = await asyncio.to_thread(windows_net.restart_windows_service, srv)
                out_str = res.get("output", "")
                err_str = res.get("error", "")
                exit_code = int(res.get("exit_code", 0 if res.get("success") else 1))

            elif tool_id == "get_service_status":
                srv = str(exec_args.get("service_name") or "").strip()
                if srv not in ["Spooler", "Dhcp", "Dnscache", "WlanSvc"]:
                    return "FAILED", 1, "", f"Service '{srv}' is not in inspected service allowlist.", "NOT_RESOLVED", {}
                services = await asyncio.to_thread(windows_net.get_critical_services)
                out_str = json.dumps({srv: services.get(srv, {"status": "Unknown"})}, indent=2)
                exit_code = 0

            elif tool_id in ["collect_network_status", "verify_network_connectivity"]:
                evidence = await asyncio.to_thread(windows_net.collect_live_windows_evidence)
                out_str = json.dumps(evidence, indent=2)
                exit_code = 0

            else:
                return "FAILED", 1, "", f"No execution handler for tool '{tool_id}'.", "NOT_RESOLVED", {}

            exec_status = "SUCCESS" if exit_code == 0 else "FAILED"

            # Postcondition verification: If execution failed, verification CANNOT be resolved!
            if exec_status == "FAILED":
                v_status = "NOT_RESOLVED"
                v_evidence = {
                    "error": "Execution failed before postcondition verification",
                    "exit_code": exit_code,
                    "details": (err_str or out_str).strip()
                }
            else:
                v_status, v_evidence = await verification_engine.verify(
                    tool_id=tool_id,
                    verification_type=tool.verification_type,
                    arguments=exec_args,
                    is_mock=False
                )

            combined_out = out_str.strip()
            if err_str.strip() and err_str.strip() not in combined_out:
                combined_out = f"{combined_out}\n[ERROR] {err_str.strip()}".strip() if combined_out else err_str.strip()
            final_output = combined_out or "Command executed."
            return exec_status, exit_code, final_output[:2000], err_str[:1000], v_status, v_evidence

        except asyncio.TimeoutError:
            return "FAILED", 124, "", f"Execution timed out after {tool.default_timeout_seconds} seconds.", "NOT_RESOLVED", {"error": "timeout"}
        except Exception as e:
            return "FAILED", 1, "", str(e), "VERIFICATION_ERROR", {"error": str(e)}


remediation_executor = RemediationExecutor()
