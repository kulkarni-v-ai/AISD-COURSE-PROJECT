import base64
import ctypes
import json
import platform
import re
import socket
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional, Tuple


VIRTUAL_ADAPTER_KEYWORDS = (
    "virtual",
    "hyper-v",
    "vethernet",
    "vmware",
    "virtualbox",
    "wsl",
    "vpn",
    "loopback",
    "bluetooth",
    "teredo",
    "6to4",
    "isatap",
    "wi-fi direct",
    "wan miniport",
    "tap-",
    "wintun",
    "wireguard",
    "tailscale",
    "zerotier",
    "nordlynx",
    "radmin",
    "hamachi",
    "npcap",
)


def is_windows() -> bool:
    return platform.system().lower() == "windows"


def is_admin() -> bool:
    if not is_windows():
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin() != 0)
    except Exception:
        return False


def _prefix_length_to_netmask(prefix_len: Optional[int]) -> Optional[str]:
    if prefix_len is None:
        return None
    try:
        bits = int(prefix_len)
        if bits < 0 or bits > 32:
            return None
        mask = (0xFFFFFFFF << (32 - bits)) & 0xFFFFFFFF
        return ".".join(str((mask >> (8 * i)) & 0xFF) for i in reversed(range(4)))
    except Exception:
        return None


def _run_powershell(script: str, timeout: float = 10.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _ps_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _build_encoded_ps(inner_commands: str) -> str:
    wrapped = (
        "$ErrorActionPreference = 'Continue';\n"
        f"{inner_commands}\n"
        "if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { exit $LASTEXITCODE } else { exit 0 }"
    )
    return base64.b64encode(wrapped.encode("utf-16-le")).decode("ascii")


def _run_elevated_powershell(inner_commands: str, timeout: float = 35.0) -> Tuple[int, str]:
    """
    Triggers UAC RunAs elevation for allowlisted commands when running non-elevated.
    Uses UTF-16LE -EncodedCommand to prevent Start-Process argument quoting bugs.
    Returns (exit_code, message).
    """
    encoded_cmd = _build_encoded_ps(inner_commands)
    outer_script = (
        f"$p = Start-Process -FilePath 'powershell.exe' "
        f"-ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand','{encoded_cmd}') "
        f"-Verb RunAs -WindowStyle Hidden -PassThru; "
        f"if ($p) {{ try {{ $null = $p.Handle }} catch {{}}; $p.WaitForExit(); exit ([int]$p.ExitCode) }} else {{ exit 1 }}"
    )
    try:
        res = _run_powershell(outer_script, timeout=timeout)
        if res.returncode == 0:
            return 0, "Elevated execution completed."
        return res.returncode or 1, (res.stderr or res.stdout or f"Elevation cancelled or failed (exit={res.returncode}).").strip()
    except subprocess.TimeoutExpired:
        return 1, f"Elevation prompt timed out after {int(timeout)}s."
    except Exception as exc:
        return 1, f"Elevation failed: {exc}"


def list_adapters() -> List[Dict[str, Any]]:
    """Enumerates Windows network adapters using Get-NetAdapter."""
    if not is_windows():
        return [{"name": "eth0", "description": "Ethernet", "status": "Up", "media_state": 1, "mac_address": "", "is_virtual": False}]

    ps_script = (
        "Get-NetAdapter | Select-Object Name, InterfaceDescription, "
        "@{N='Status';E={$_.Status.ToString()}}, "
        "@{N='MediaState';E={[int]$_.MediaConnectionState}}, "
        "MacAddress | ConvertTo-Json -Compress"
    )
    try:
        res = _run_powershell(ps_script, timeout=8.0)
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout)
            if isinstance(data, dict):
                data = [data]
            results: List[Dict[str, Any]] = []
            for item in data:
                name = str(item.get("Name") or "")
                desc = str(item.get("InterfaceDescription") or "")
                combined = f"{name} {desc}".lower()
                is_virtual = any(k in combined for k in VIRTUAL_ADAPTER_KEYWORDS)
                results.append(
                    {
                        "name": name,
                        "description": desc,
                        "status": str(item.get("Status") or "Unknown"),
                        "media_state": int(item.get("MediaState") or 0),
                        "mac_address": str(item.get("MacAddress") or ""),
                        "is_virtual": is_virtual,
                    }
                )
            return results
    except Exception:
        pass
    return []


def resolve_active_adapter(
    requested_name: Optional[str] = None,
    adapters: Optional[List[Dict[str, Any]]] = None,
) -> Optional[str]:
    """
    Resolves the real Windows physical adapter name.
    Falls back to the active physical Wi-Fi/Ethernet adapter when a generic default
    like 'Wi-Fi' does not exist on the host (e.g., resolves to 'Wi-Fi 2').
    """
    adapter_list = adapters if adapters is not None else list_adapters()
    if not adapter_list:
        return requested_name or "Wi-Fi"

    req_clean = (requested_name or "").strip()
    if req_clean and req_clean.lower() not in {"auto", "default"}:
        for item in adapter_list:
            if item.get("name", "").lower() == req_clean.lower():
                return item["name"]

    physical = [a for a in adapter_list if not a.get("is_virtual", False)]
    physical_up = [a for a in physical if str(a.get("status", "")).lower() == "up"]

    for group in (physical_up, physical):
        for item in group:
            combined = f"{item.get('name', '')} {item.get('description', '')}".lower()
            if "wi-fi" in combined or "wifi" in combined or "wlan" in combined or "wireless" in combined:
                return item["name"]
        if group:
            return group[0]["name"]

    for item in adapter_list:
        if str(item.get("status", "")).lower() == "up":
            return item["name"]

    return adapter_list[0].get("name")


def get_primary_adapter_details(adapters: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    adapter_list = adapters if adapters is not None else list_adapters()
    resolved = resolve_active_adapter(None, adapters=adapter_list)
    if resolved:
        for item in adapter_list:
            if item.get("name") == resolved:
                return item
    return {"name": resolved or "Wi-Fi", "status": "Disabled", "description": "No network adapter detected", "is_virtual": False}


def parse_netsh_dns_output(output: str) -> Dict[str, Any]:
    """Parses `netsh interface ipv4 show dnsservers` output cleanly."""
    text = output or ""
    lower = text.lower()
    is_static = "statically configured dns servers" in lower
    is_dhcp = "configured through dhcp" in lower

    ips: List[str] = []
    capture = False
    for line in text.splitlines():
        l_lower = line.lower()
        if "dns servers" in l_lower or "configured through dhcp" in l_lower:
            capture = True
        elif "register with which suffix" in l_lower:
            capture = False

        if capture:
            found = re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", line)
            for ip in found:
                if ip not in ips:
                    ips.append(ip)

    if not is_static and not is_dhcp:
        # Unknown/absent adapter output; default conservatively
        dns_dhcp_enabled = True
    else:
        dns_dhcp_enabled = not is_static

    return {
        "dns_dhcp_enabled": dns_dhcp_enabled,
        "static_dns_configured": is_static,
        "dns_servers": ips,
        "raw": text.strip(),
    }


def get_dns_server_config(adapter_name: str) -> Dict[str, Any]:
    """Inspects whether DNS servers on the given adapter are static or DHCP-assigned."""
    if not is_windows() or not adapter_name:
        return {"dns_dhcp_enabled": True, "static_dns_configured": False, "dns_servers": [], "raw": ""}

    try:
        res = subprocess.run(
            ["netsh", "interface", "ipv4", "show", "dnsservers", f"name={adapter_name}"],
            capture_output=True,
            text=True,
            timeout=6,
        )
        parsed = parse_netsh_dns_output((res.stdout or "") + "\n" + (res.stderr or ""))
        parsed["adapter_name"] = adapter_name
        return parsed
    except Exception as exc:
        return {
            "adapter_name": adapter_name,
            "dns_dhcp_enabled": True,
            "static_dns_configured": False,
            "dns_servers": [],
            "error": str(exc),
        }


def get_ip_config_for_adapter(adapter_name: Optional[str] = None) -> Dict[str, Any]:
    """Collects accurate IPv4, prefix/subnet mask, gateway, DHCP state, and DNS mode for an adapter."""
    target = resolve_active_adapter(adapter_name)
    if not target:
        return {
            "adapter_name": None,
            "ipv4_address": None,
            "subnet_mask": None,
            "default_gateway": None,
            "dhcp_enabled": True,
            "dns_dhcp_enabled": True,
            "dns_servers": [],
            "is_apipa": False,
            "has_valid_ip": False,
        }

    dns_info = get_dns_server_config(target)

    if not is_windows():
        return {
            "adapter_name": target,
            "ipv4_address": None,
            "subnet_mask": None,
            "default_gateway": None,
            "dhcp_enabled": True,
            "dns_dhcp_enabled": dns_info.get("dns_dhcp_enabled", True),
            "dns_servers": dns_info.get("dns_servers", []),
            "is_apipa": False,
            "has_valid_ip": False,
        }

    q_name = _ps_quote(target)
    ps_script = (
        f"$i = Get-NetIPInterface -InterfaceAlias {q_name} -AddressFamily IPv4 -ErrorAction SilentlyContinue | Select-Object -First 1; "
        f"$c = Get-NetIPConfiguration -InterfaceAlias {q_name} -ErrorAction SilentlyContinue | Select-Object -First 1; "
        "$ipObj = $c.IPv4Address | Select-Object -First 1; "
        "$gwObj = $c.IPv4DefaultGateway | Select-Object -First 1; "
        "$dnsObj = $c.DNSServer | Where-Object { $_.AddressFamily -eq 2 } | Select-Object -First 1; "
        "[PSCustomObject]@{"
        " dhcp = if ($i) { $i.Dhcp.ToString() } else { 'Unknown' };"
        " ip = if ($ipObj) { $ipObj.IPAddress } else { $null };"
        " prefix = if ($ipObj) { [int]$ipObj.PrefixLength } else { $null };"
        " gw = if ($gwObj) { $gwObj.NextHop } else { $null };"
        " dns = if ($dnsObj) { @($dnsObj.ServerAddresses) } else { @() }"
        "} | ConvertTo-Json -Compress"
    )
    ipv4 = None
    subnet_mask = None
    gateway = None
    dhcp_enabled = True
    dns_servers = dns_info.get("dns_servers", [])

    try:
        res = _run_powershell(ps_script, timeout=8.0)
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout)
            ipv4 = data.get("ip")
            subnet_mask = _prefix_length_to_netmask(data.get("prefix"))
            gateway = data.get("gw")
            dhcp_str = str(data.get("dhcp") or "").strip().lower()
            if dhcp_str == "disabled":
                dhcp_enabled = False
            elif dhcp_str == "enabled":
                dhcp_enabled = True
            if not dns_servers and isinstance(data.get("dns"), list):
                dns_servers = [str(d) for d in data["dns"] if d]
    except Exception:
        pass

    return {
        "adapter_name": target,
        "ipv4_address": ipv4,
        "subnet_mask": subnet_mask,
        "default_gateway": gateway,
        "dhcp_enabled": dhcp_enabled,
        "dns_dhcp_enabled": dns_info.get("dns_dhcp_enabled", True),
        "static_dns_configured": dns_info.get("static_dns_configured", False),
        "dns_servers": dns_servers,
        "is_apipa": bool(ipv4 and str(ipv4).startswith("169.254.")),
        "has_valid_ip": bool(ipv4 and not str(ipv4).startswith("169.254.") and not str(ipv4).startswith("127.")),
    }


def ping_host(target: str, count: int = 3, timeout_ms: int = 1000) -> Dict[str, Any]:
    if not target:
        return {"reachable": False, "packet_loss_pct": 100, "avg_latency_ms": None, "note": "No target host configured."}
    try:
        cmd = ["ping", "-n", str(count), "-w", str(timeout_ms), target] if is_windows() else ["ping", "-c", str(count), target]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=max(6, count * 2 + 2))
        reachable = res.returncode == 0
        out = res.stdout or ""

        loss_match = re.search(r"\((\d+)%\s*(?:packet\s*)?loss\)", out, re.IGNORECASE)
        loss = int(loss_match.group(1)) if loss_match else (0 if reachable else 100)

        lat_match = re.search(r"Average\s*=\s*(\d+)ms", out, re.IGNORECASE)
        avg_lat = int(lat_match.group(1)) if lat_match else None

        return {
            "target": target,
            "reachable": reachable,
            "packet_loss_pct": loss,
            "avg_latency_ms": avg_lat,
            "raw_output": out.strip()[:500],
        }
    except Exception as exc:
        return {"target": target, "reachable": False, "packet_loss_pct": 100, "avg_latency_ms": None, "error": str(exc)}


def test_dns_hosts(domains: Optional[List[str]] = None, adapter_name: Optional[str] = None) -> Dict[str, Any]:
    targets = domains or ["college.edu", "google.com"]
    per_domain: Dict[str, Any] = {}
    any_resolved = False
    all_resolved = True

    for dom in targets:
        try:
            infos = socket.getaddrinfo(dom, None)
            addrs = list(dict.fromkeys(info[4][0] for info in infos if info and info[4]))
            per_domain[dom] = {"resolved": bool(addrs), "addresses": addrs[:4]}
            if addrs:
                any_resolved = True
            else:
                all_resolved = False
        except Exception as exc:
            per_domain[dom] = {"resolved": False, "error": str(exc)}
            all_resolved = False

    target = resolve_active_adapter(adapter_name)
    dns_cfg = get_dns_server_config(target) if target else {"dns_dhcp_enabled": True, "dns_servers": []}

    primary = targets[0]
    primary_res = per_domain.get(primary, {})
    return {
        "resolved": any_resolved,
        "all_resolved": all_resolved,
        "target_domain": primary,
        "resolved_ip": (primary_res.get("addresses") or [None])[0],
        "public_dns_resolved": per_domain.get("google.com", {}).get("resolved", False),
        "domains": per_domain,
        "dns_dhcp_enabled": dns_cfg.get("dns_dhcp_enabled", True),
        "dns_servers": dns_cfg.get("dns_servers", []),
    }


def get_firewall_status() -> Dict[str, Any]:
    if not is_windows():
        return {"Domain": True, "Private": True, "Public": True}
    try:
        res = _run_powershell("Get-NetFirewallProfile | Select-Object Name, Enabled | ConvertTo-Json -Compress", timeout=6.0)
        if res.returncode == 0 and res.stdout.strip():
            profiles = json.loads(res.stdout)
            if isinstance(profiles, dict):
                profiles = [profiles]
            return {str(p.get("Name")): bool(p.get("Enabled")) for p in profiles}
    except Exception:
        pass
    return {"Domain": True, "Private": True, "Public": True}


def get_critical_services() -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    if not is_windows():
        return results
    try:
        res = _run_powershell(
            "Get-Service -Name Spooler,Dhcp,Dnscache,WlanSvc -ErrorAction SilentlyContinue | "
            "Select-Object Name, @{N='Status';E={$_.Status.ToString()}} | ConvertTo-Json -Compress",
            timeout=6.0,
        )
        if res.returncode == 0 and res.stdout.strip():
            items = json.loads(res.stdout)
            if isinstance(items, dict):
                items = [items]
            for item in items:
                results[str(item.get("Name"))] = {"status": str(item.get("Status") or "Unknown")}
    except Exception:
        pass
    for srv in ("Spooler", "Dhcp", "Dnscache", "WlanSvc"):
        if srv not in results:
            results[srv] = {"status": "Unknown"}
    return results


def collect_live_windows_evidence(target_domain: str = "college.edu") -> Dict[str, Any]:
    """Collects live Windows telemetry covering all AISD diagnostic checks."""
    adapters = list_adapters()
    primary_adapter = get_primary_adapter_details(adapters)
    adapter_name = primary_adapter.get("name")
    ip_config = get_ip_config_for_adapter(adapter_name)

    gw_ip = ip_config.get("default_gateway")
    gateway_ping = ping_host(gw_ip, count=3, timeout_ms=1000) if gw_ip else {
        "reachable": False,
        "packet_loss_pct": 100,
        "avg_latency_ms": None,
        "target_gateway": None,
        "note": "No default gateway configured.",
    }
    if "target_gateway" not in gateway_ping:
        gateway_ping["target_gateway"] = gw_ip

    internet_ping = ping_host("8.8.8.8", count=3, timeout_ms=1000)
    internet_ping["target_ip"] = "8.8.8.8"
    avg_lat = internet_ping.get("avg_latency_ms")
    internet_ping["high_latency"] = bool(avg_lat and avg_lat > 5000)
    internet_ping["high_packet_loss"] = bool(internet_ping.get("packet_loss_pct", 0) > 20)

    dns_test = test_dns_hosts([target_domain, "google.com"], adapter_name=adapter_name)
    firewall = get_firewall_status()
    services = get_critical_services()

    return {
        "network_adapter": primary_adapter,
        "adapters_list": adapters,
        "ip_config": ip_config,
        "gateway_ping": gateway_ping,
        "internet_ping": internet_ping,
        "dns_test": dns_test,
        "firewall": firewall,
        "services": services,
    }


def flush_dns_resolver_cache() -> Tuple[bool, str]:
    """Flushes the local Windows DNS client resolver cache."""
    if not is_windows():
        return True, "Non-Windows OS: DNS flush simulated as no-op."

    try:
        res = ctypes.windll.dnsapi.DnsFlushResolverCache()
        if res != 0:
            return True, "Flushed Windows DNS resolver cache via Win32 DnsFlushResolverCache API."
    except Exception:
        pass

    try:
        ps = _run_powershell("Clear-DnsClientCache", timeout=10.0)
        if ps.returncode == 0:
            return True, "Flushed Windows DNS resolver cache via Clear-DnsClientCache."
        return False, (ps.stderr or ps.stdout or "Clear-DnsClientCache failed.").strip()
    except Exception as exc:
        return False, f"DNS cache flush failed: {exc}"


def reset_dns_to_dhcp_and_flush(adapter_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Resets manually configured static DNS servers back to DHCP on the active physical
    adapter and flushes/re-registers the Windows DNS resolver cache.
    Never claims success if static DNS remains active afterward.
    """
    adapter = resolve_active_adapter(adapter_name)
    if not adapter:
        return {
            "success": False,
            "exit_code": 1,
            "adapter_name": None,
            "output": "",
            "error": "No valid Windows network adapter found.",
        }

    pre_dns = get_dns_server_config(adapter)
    logs: List[str] = [
        f"Target adapter: {adapter}",
        f"Pre-remediation DNS mode: {'DHCP (Automatic)' if pre_dns.get('dns_dhcp_enabled') else 'Static (' + ', '.join(pre_dns.get('dns_servers', [])) + ')'}",
    ]

    if not is_windows():
        return {"success": True, "exit_code": 0, "adapter_name": adapter, "output": "\n".join(logs), "error": ""}

    static_was_set = pre_dns.get("static_dns_configured", False)
    if static_was_set:
        res = subprocess.run(
            ["netsh", "interface", "ipv4", "set", "dnsservers", f"name={adapter}", "source=dhcp"],
            capture_output=True,
            text=True,
            timeout=12,
        )
        cmd_out = (res.stdout or res.stderr or "").strip()
        if cmd_out:
            logs.append(f"netsh set dnsservers source=dhcp: {cmd_out}")

        combined_lower = cmd_out.lower()
        if res.returncode != 0 and ("requires elevation" in combined_lower or "administrator" in combined_lower or not is_admin()):
            q_name = _ps_quote(adapter)
            elev_code, elev_msg = _run_elevated_powershell(
                f"$iface = {q_name}; & netsh.exe interface ipv4 set dnsservers ('name=' + $iface) source=dhcp | Out-Null",
                timeout=35.0,
            )
            logs.append(f"Elevated UAC invocation (exit={elev_code}): {elev_msg}")

    flush_ok, flush_msg = flush_dns_resolver_cache()
    logs.append(flush_msg)

    if is_admin():
        try:
            reg_res = subprocess.run(["ipconfig", "/registerdns"], capture_output=True, text=True, timeout=10)
            reg_msg = (reg_res.stdout or reg_res.stderr or "").strip()
            if reg_msg:
                logs.append(f"ipconfig /registerdns: {reg_msg.splitlines()[0]}")
        except Exception:
            pass

    time.sleep(0.5)
    post_dns = get_dns_server_config(adapter)
    logs.append(
        f"Post-remediation DNS mode: {'DHCP (Automatic)' if post_dns.get('dns_dhcp_enabled') else 'Static (' + ', '.join(post_dns.get('dns_servers', [])) + ')'}"
    )

    if post_dns.get("static_dns_configured"):
        err = (
            f"Static DNS servers ({', '.join(post_dns.get('dns_servers', []))}) are still configured on '{adapter}'. "
            "Windows Administrator privileges are required to reset DNS back to automatic DHCP. "
            "Start AISD via RUN_AISD.bat (Run as Administrator)."
        )
        return {
            "success": False,
            "exit_code": 1,
            "adapter_name": adapter,
            "output": "\n".join(logs),
            "error": err,
            "post_dns": post_dns,
        }

    if not flush_ok:
        return {
            "success": False,
            "exit_code": 1,
            "adapter_name": adapter,
            "output": "\n".join(logs),
            "error": flush_msg,
            "post_dns": post_dns,
        }

    return {
        "success": True,
        "exit_code": 0,
        "adapter_name": adapter,
        "output": "\n".join(logs),
        "error": "",
        "post_dns": post_dns,
    }


def renew_dhcp_for_adapter(adapter_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Switches static IPv4 and static DNS settings back to DHCP on the active physical
    adapter using netsh, renews the DHCP lease with ipconfig /renew <adapter>,
    and verifies the resulting OS network configuration.
    """
    adapter = resolve_active_adapter(adapter_name)
    if not adapter:
        return {
            "success": False,
            "exit_code": 1,
            "adapter_name": None,
            "output": "",
            "error": "No valid Windows network adapter found.",
        }

    if not is_windows():
        return {"success": True, "exit_code": 0, "adapter_name": adapter, "output": f"Non-Windows DHCP renew no-op on {adapter}", "error": ""}

    pre_ip = get_ip_config_for_adapter(adapter)
    logs: List[str] = [
        f"Resolved active physical adapter: {adapter}",
        f"Pre-remediation IPv4={pre_ip.get('ipv4_address')} Gateway={pre_ip.get('default_gateway')} DHCP={'Enabled' if pre_ip.get('dhcp_enabled') else 'Disabled'} StaticDNS={pre_ip.get('static_dns_configured')}",
    ]

    need_elevation = False

    if pre_ip.get("dhcp_enabled") is False:
        res_ip = subprocess.run(
            ["netsh", "interface", "ipv4", "set", "address", f"name={adapter}", "source=dhcp"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        out_ip = (res_ip.stdout or res_ip.stderr or "").strip()
        if out_ip:
            logs.append(f"netsh set address source=dhcp: {out_ip}")
        if res_ip.returncode != 0 and ("already enabled" not in out_ip.lower()):
            if "requires elevation" in out_ip.lower() or "administrator" in out_ip.lower() or not is_admin():
                need_elevation = True

    if pre_ip.get("static_dns_configured"):
        res_dns = subprocess.run(
            ["netsh", "interface", "ipv4", "set", "dnsservers", f"name={adapter}", "source=dhcp"],
            capture_output=True,
            text=True,
            timeout=12,
        )
        out_dns = (res_dns.stdout or res_dns.stderr or "").strip()
        if out_dns:
            logs.append(f"netsh set dnsservers source=dhcp: {out_dns}")
        if res_dns.returncode != 0 and ("requires elevation" in out_dns.lower() or "administrator" in out_dns.lower() or not is_admin()):
            need_elevation = True

    if need_elevation and not is_admin():
        q_name = _ps_quote(adapter)
        cmds = "\n".join(
            [
                f"$iface = {q_name}",
                "& netsh.exe interface ipv4 set address ('name=' + $iface) source=dhcp | Out-Null",
                "& netsh.exe interface ipv4 set dnsservers ('name=' + $iface) source=dhcp | Out-Null",
                "& ipconfig.exe /renew $iface | Out-Null",
            ]
        )
        elev_code, elev_msg = _run_elevated_powershell(cmds, timeout=35.0)
        logs.append(f"Elevated RunAs DHCP remediation (exit={elev_code}): {elev_msg}")
    else:
        res_renew = subprocess.run(
            ["ipconfig", "/renew", adapter],
            capture_output=True,
            text=True,
            timeout=20,
        )
        out_renew = (res_renew.stdout or res_renew.stderr or "").strip()
        if out_renew:
            logs.append(f"ipconfig /renew \"{adapter}\": {out_renew}")
        if res_renew.returncode != 0 and ("requires elevation" in out_renew.lower() or "administrator" in out_renew.lower()) and not is_admin():
            q_name = _ps_quote(adapter)
            elev_code, elev_msg = _run_elevated_powershell(
                f"$iface = {q_name}; & ipconfig.exe /renew $iface | Out-Null",
                timeout=30.0
            )
            logs.append(f"Elevated RunAs ipconfig /renew (exit={elev_code}): {elev_msg}")

    flush_ok, flush_msg = flush_dns_resolver_cache()
    logs.append(flush_msg)

    # Allow DHCP lease and route assignment to settle briefly before verifying
    post_ip = get_ip_config_for_adapter(adapter)
    for _ in range(3):
        if post_ip.get("dhcp_enabled") and post_ip.get("has_valid_ip") and post_ip.get("default_gateway"):
            break
        time.sleep(1.0)
        post_ip = get_ip_config_for_adapter(adapter)

    logs.append(
        f"Post-remediation IPv4={post_ip.get('ipv4_address')} Gateway={post_ip.get('default_gateway')} DHCP={'Enabled' if post_ip.get('dhcp_enabled') else 'Disabled'} StaticDNS={post_ip.get('static_dns_configured')}"
    )

    if post_ip.get("dhcp_enabled") is False:
        err = (
            f"Adapter '{adapter}' still has Static IP configuration (DHCP disabled). "
            "Administrator privileges are required to switch IPv4 to DHCP. "
            "Launch AISD using RUN_AISD.bat as Administrator."
        )
        return {
            "success": False,
            "exit_code": 1,
            "adapter_name": adapter,
            "output": "\n".join(logs),
            "error": err,
            "post_ip": post_ip,
        }

    return {
        "success": True,
        "exit_code": 0,
        "adapter_name": adapter,
        "output": "\n".join(logs),
        "error": "",
        "post_ip": post_ip,
    }


def enable_network_adapter(adapter_name: Optional[str] = None) -> Dict[str, Any]:
    adapter = resolve_active_adapter(adapter_name)
    if not adapter:
        return {"success": False, "exit_code": 1, "adapter_name": None, "output": "", "error": "No adapter found."}
    if not is_windows():
        return {"success": True, "exit_code": 0, "adapter_name": adapter, "output": f"Simulated enable {adapter}", "error": ""}

    q_name = _ps_quote(adapter)
    cmd_str = f"Enable-NetAdapter -Name {q_name} -Confirm:$false"
    res = _run_powershell(cmd_str, timeout=15.0)
    out = (res.stdout or res.stderr or "").strip()

    if res.returncode != 0 and ("access" in out.lower() or "denied" in out.lower() or "permission" in out.lower() or not is_admin()):
        elev_cmds = (
            f"$iface = {q_name}; "
            f"Enable-NetAdapter -Name $iface -Confirm:$false -ErrorAction SilentlyContinue; "
            f"& netsh.exe interface set interface ('name=' + $iface) admin=enabled | Out-Null"
        )
        elev_code, elev_msg = _run_elevated_powershell(elev_cmds, timeout=35.0)
        out = f"{out}\nElevated Enable-NetAdapter (exit={elev_code}): {elev_msg}".strip()

    status = "Unknown"
    for _ in range(6):
        chk = _run_powershell(f"(Get-NetAdapter -Name {q_name} -ErrorAction SilentlyContinue).Status.ToString()", timeout=6.0)
        status = (chk.stdout or "").strip() or "Unknown"
        if status.lower() == "up":
            break
        time.sleep(1.0)

    ok = status.lower() == "up"
    return {
        "success": ok,
        "exit_code": 0 if ok else 1,
        "adapter_name": adapter,
        "output": out or f"Adapter '{adapter}' status: {status or 'Unknown'}",
        "error": "" if ok else f"Adapter '{adapter}' status after enable attempt is '{status or 'Unknown'}'.",
    }


def restart_windows_service(service_name: str) -> Dict[str, Any]:
    allowed = {"Spooler", "Dhcp", "Dnscache"}
    if service_name not in allowed:
        return {
            "success": False,
            "exit_code": 1,
            "output": "",
            "error": f"Service '{service_name}' is not in approved restart allowlist.",
        }
    if not is_windows():
        return {"success": True, "exit_code": 0, "output": f"Restarted {service_name}", "error": ""}

    q_srv = _ps_quote(service_name)
    cmd_str = f"Restart-Service -Name {q_srv} -Force"
    res = _run_powershell(cmd_str, timeout=15.0)
    out = (res.stdout or res.stderr or "").strip()
    if res.returncode != 0 and not is_admin():
        elev_code, elev_msg = _run_elevated_powershell(f"Restart-Service -Name {q_srv} -Force -ErrorAction Stop", timeout=30.0)
        out = f"{out}\nElevated Restart-Service (exit={elev_code}): {elev_msg}".strip()

    status = "Unknown"
    for _ in range(3):
        chk = _run_powershell(f"(Get-Service -Name {q_srv} -ErrorAction SilentlyContinue).Status.ToString()", timeout=6.0)
        status = (chk.stdout or "").strip() or "Unknown"
        if status.lower() == "running":
            break
        time.sleep(0.8)
    ok = status.lower() == "running"
    return {
        "success": ok,
        "exit_code": 0 if ok else 1,
        "output": out or f"Service '{service_name}' state: {status or 'Unknown'}",
        "error": "" if ok else f"Service '{service_name}' is '{status or 'Unknown'}' (expected Running).",
    }
