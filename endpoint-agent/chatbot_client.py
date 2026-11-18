#!/usr/bin/env python3
"""
AISD Interactive IT Assistant & Chatbot Client
Cross-Platform (Windows & Linux) CLI Chatbot for VM and Physical Endpoints.
Supports:
  - Online Chat via Central Server RAG + Ollama Load Balancer
  - Dynamic Offline Fallback to Local Deterministic Engine & Local SOPs
  - Local Live Telemetry Diagnostics and Allowlisted Remediation
"""

import os
import sys
import json
import time
import argparse
from typing import List, Dict, Any, Optional
import httpx

from agent_config import agent_config
from storage import AgentLocalStorage
from diagnostics import EndpointDiagnostics
from rules import local_rule_engine
from remediation import LocalRemediationPolicy
from sync import EndpointSyncService
from agent import run_offline_workflow

# ANSI color codes
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"


def print_banner(server_url: str, is_online: bool) -> None:
    print(f"\n{CYAN}{BOLD}=================================================================={RESET}")
    print(f"{CYAN}{BOLD}   AISD — AI IT Support Chatbot Client (Cross-Platform)          {RESET}")
    print(f"{CYAN}{BOLD}=================================================================={RESET}")
    print(f" Agent UUID : {agent_config.agent_uuid}")
    print(f" Hostname   : {agent_config.hostname}")
    print(f" Platform   : {agent_config.os_name} ({agent_config.os_version})")
    status_str = f"{GREEN}ONLINE (Connected){RESET}" if is_online else f"{RED}OFFLINE (Local Mode){RESET}"
    print(f" Server URL : {server_url} [{status_str}]")
    print(f"{CYAN}------------------------------------------------------------------{RESET}")
    print(" Type your IT problem naturally, or use commands:")
    print(f"   {BOLD}/diagnose{RESET}  - Run instant local diagnostic telemetry scan")
    print(f"   {BOLD}/fix{RESET}       - Execute allowlisted remediation & postcondition verification")
    print(f"   {BOLD}/status{RESET}    - Check server connectivity, load balancer & local outbox")
    print(f"   {BOLD}/sync{RESET}      - Manually flush local offline outbox to central server")
    print(f"   {BOLD}/help{RESET}      - Show command list")
    print(f"   {BOLD}/quit{RESET}      - Exit chatbot")
    print(f"{CYAN}=================================================================={RESET}\n")


# Local SOP procedures for offline chatbot advice
LOCAL_SOPS = [
    {
        "id": "KB-NET-001",
        "keywords": ["169.254", "apipa", "dhcp", "no internet", "lease", "ip"],
        "title": "DHCP Lease Failure & APIPA (169.254.x.x) Recovery SOP",
        "action": "renew_dhcp",
        "guidance": "Your adapter is using an unroutable APIPA 169.254.x.x address. Execute `renew_dhcp` or type `/fix` to obtain a fresh lease from the campus network."
    },
    {
        "id": "KB-NET-003",
        "keywords": ["dns", "resolve", "domain", "nxdomain", "lookup"],
        "title": "DNS Resolution Failure SOP",
        "action": "flush_dns_cache",
        "guidance": "Local DNS cache or resolver is unresponsive. Execute `flush_dns_cache` or type `/fix` to clear stale entries."
    },
    {
        "id": "KB-PRT-001",
        "keywords": ["printer", "print", "spooler", "cups"],
        "title": "Print Service Stoppage Recovery SOP",
        "action": "restart_approved_service",
        "guidance": "The printing spooler service is stopped. Type `/fix` to safely restart the approved service."
    },
    {
        "id": "KB-NET-004",
        "keywords": ["adapter", "disabled", "down", "disconnected"],
        "title": "Network Adapter Disabled SOP",
        "action": "enable_adapter",
        "guidance": "The network interface is currently disabled. Type `/fix` to re-enable it."
    }
]


def answer_offline(query: str) -> Dict[str, Any]:
    """Generates deterministic RAG-grounded response when central server is unreachable."""
    q_lower = query.lower()
    matched = []
    for sop in LOCAL_SOPS:
        if any(k in q_lower for k in sop["keywords"]):
            matched.append(sop)

    if matched:
        top = matched[0]
        reply = (
            f"⚡ [OFFLINE LOCAL ADVISOR]\n"
            f"Identified SOP: [{top['id']}] {top['title']}\n\n"
            f"Guidance: {top['guidance']}\n"
            f"Recommended Action: Tool `{top['action']}`\n"
            f"(You can type `/fix` to automatically execute this fix and verify postconditions)."
        )
        return {
            "reply": reply,
            "sources": [{"doc_id": top["id"], "title": top["title"]}],
            "provider": "local_offline_sop_engine"
        }

    return {
        "reply": (
            "⚡ [OFFLINE LOCAL ADVISOR]\n"
            "Central AI server is offline. No specific offline SOP matched your query.\n"
            "Tip: Type `/diagnose` to inspect local network interfaces, or `/fix` to evaluate local rules."
        ),
        "sources": [],
        "provider": "local_offline_sop_engine"
    }


def main():
    parser = argparse.ArgumentParser(description="AISD IT Incident Assistant Chatbot Client")
    parser.add_argument("--server", type=str, default=agent_config.server_url, help="Central Server URL")
    parser.add_argument("--offline", action="store_true", help="Force offline mode")
    args = parser.parse_args()

    server_url = args.server.rstrip("/")
    storage = AgentLocalStorage(agent_config.db_path)
    sync_svc = EndpointSyncService(storage, server_url=server_url)

    is_online = (not args.offline) and sync_svc.is_server_reachable()
    print_banner(server_url, is_online)

    history: List[Dict[str, str]] = []

    while True:
        try:
            # Dynamic reachability check
            current_online = (not args.offline) and sync_svc.is_server_reachable()
            if current_online != is_online:
                is_online = current_online
                if is_online:
                    print(f"\n{GREEN}⚡ [STATUS CHANGE] Central Server connected! Switched to ONLINE mode.{RESET}\n")
                else:
                    print(f"\n{YELLOW}🔌 [STATUS CHANGE] Central Server unreachable. Switched to OFFLINE mode.{RESET}\n")

            prompt_symbol = f"{GREEN}AISD-Online>{RESET} " if is_online else f"{YELLOW}AISD-Offline>{RESET} "
            user_input = input(prompt_symbol).strip()

            if not user_input:
                continue

            # Command Handling
            if user_input.lower() in ("/quit", "/exit", "exit", "quit"):
                print("\nGoodbye!\n")
                break

            elif user_input.lower() == "/help":
                print(f"\n{BOLD}Available Commands:{RESET}")
                print("  /diagnose - Run live hardware/network diagnostic collection")
                print("  /fix      - Run allowlisted remediation & postcondition verification")
                print("  /status   - Display agent and server network state")
                print("  /sync     - Flush local queued outbox to central server")
                print("  /clear    - Clear screen")
                print("  /help     - Show this help message")
                print("  /quit     - Exit chatbot\n")
                continue

            elif user_input.lower() == "/clear":
                os.system("cls" if os.name == "nt" else "clear")
                print_banner(server_url, is_online)
                continue

            elif user_input.lower() == "/status":
                pending = len(storage.get_pending_events())
                print(f"\n{BOLD}=== AISD Client Status ==={RESET}")
                print(f" Agent UUID    : {agent_config.agent_uuid}")
                print(f" Hostname      : {agent_config.hostname}")
                print(f" OS Name       : {agent_config.os_name}")
                print(f" OS Version    : {agent_config.os_version}")
                print(f" Server URL    : {server_url} [{'REACHABLE' if is_online else 'UNREACHABLE'}]")
                print(f" Queued Outbox : {pending} events in {agent_config.db_path}")

                if is_online:
                    try:
                        with httpx.Client(timeout=3.0) as client:
                            resp = client.get(f"{server_url}/api/chat/loadbalancer/status")
                            if resp.status_code == 200:
                                lb_data = resp.json()
                                print(f" Load Balancer : {lb_data.get('healthy_nodes')}/{lb_data.get('total_nodes')} healthy upstream nodes (Strategy: {lb_data.get('strategy')})")
                    except Exception:
                        pass
                print()
                continue

            elif user_input.lower() == "/diagnose":
                print(f"\n{CYAN}Collecting live diagnostic telemetry...{RESET}")
                telemetry = EndpointDiagnostics.collect_all()
                nic = telemetry.get("network_adapter", {})
                ip = telemetry.get("ip_config", {})
                gw = telemetry.get("gateway_ping", {})
                dns = telemetry.get("dns_test", {})
                srv = telemetry.get("services", {})

                print(f"\n{BOLD}--- Diagnostic Summary ---{RESET}")
                print(f" Adapter : {nic.get('name')} [{nic.get('status')}]")
                print(f" IPv4    : {ip.get('ipv4_address')} (DHCP: {ip.get('dhcp_enabled')})")
                print(f" Gateway : {ip.get('default_gateway')} [Reachable: {gw.get('reachable')}]")
                print(f" DNS     : {dns.get('resolved_ip')} [Resolved: {dns.get('resolved')}]")
                print(f" Services: {srv}")

                eval_result = local_rule_engine.evaluate(telemetry)
                print(f"\n{BOLD}Deterministic Evaluation:{RESET}")
                print(f" Status  : {eval_result.get('status')}")
                print(f" Summary : {eval_result.get('summary')}")
                if eval_result.get("recommended_tool_ids"):
                    print(f" Tools   : {eval_result.get('recommended_tool_ids')}")
                print()
                continue

            elif user_input.lower() == "/fix":
                print(f"\n{CYAN}Executing automated diagnosis, approved remediation, and verification...{RESET}")
                result = run_offline_workflow(storage)
                flag = result.get("resolution_flag") or result.get("status")
                summary = result.get("outcome_summary") or result.get("payload", {}).get("outcome_summary", "")

                if flag == "FIXED" or result.get("is_fixed"):
                    print(f"\n{GREEN}{BOLD}>>> OUTCOME: [VERIFIED FIXED]{RESET}")
                    print(f">>> {summary}\n")
                elif "CANNOT_BE_DONE" in str(flag):
                    print(f"\n{YELLOW}{BOLD}>>> OUTCOME: [CANNOT BE DONE LOCALLY - QUEUED]{RESET}")
                    print(f">>> {summary}\n")
                else:
                    print(f"\n{BOLD}>>> OUTCOME: [{flag}]{RESET}")
                    print(f">>> {summary}\n")
                continue

            elif user_input.lower() == "/sync":
                if not is_online:
                    print(f"\n{YELLOW}Cannot sync: Central Server is OFFLINE.{RESET}\n")
                else:
                    print(f"\n{CYAN}Synchronizing outbox with Central Server...{RESET}")
                    acc, dup = sync_svc.sync_outbox()
                    print(f"{GREEN}Sync complete: {acc} accepted, {dup} duplicate/already synced.{RESET}\n")
                continue

            # Standard Chat Query Handling
            if is_online:
                try:
                    payload = {
                        "message": user_input,
                        "history": history[-4:],
                        "agent_uuid": agent_config.agent_uuid
                    }
                    with httpx.Client(timeout=30.0) as client:
                        resp = client.post(f"{server_url}/api/chat/message", json=payload)
                        if resp.status_code == 200:
                            data = resp.json()
                            reply = data.get("reply", "")
                            sources = data.get("sources", [])
                            provider = data.get("provider", "online_ai")

                            print(f"\n{CYAN}{BOLD}Assistant ({provider}):{RESET}")
                            print(reply)
                            if sources:
                                print(f"\n{BOLD}Cited Procedures:{RESET}")
                                for s in sources[:3]:
                                    print(f"  • [{s.get('doc_id')}] {s.get('title')}")
                            print()

                            history.append({"role": "user", "content": user_input})
                            history.append({"role": "assistant", "content": reply})
                            continue
                except Exception as exc:
                    print(f"\n{YELLOW}[Online query failed: {exc}. Falling back to offline advisor]{RESET}")

            # Offline Fallback
            offline_res = answer_offline(user_input)
            print(f"\n{YELLOW}{BOLD}Assistant ({offline_res['provider']}):{RESET}")
            print(offline_res["reply"])
            print()

        except KeyboardInterrupt:
            print("\nExiting chatbot.")
            break
        except Exception as e:
            print(f"\n{RED}Error: {e}{RESET}\n")


if __name__ == "__main__":
    main()
