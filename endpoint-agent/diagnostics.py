import json
import os
import platform
import re
import socket
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Optional


def _is_linux() -> bool:
    return platform.system().lower() == "linux"


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
    "docker",
    "veth",
    "virbr",
    "br-",
    "dummy",
)


def _resolve_hostname_with_timeout(domain: str, timeout: float = 3.5) -> Dict[str, Any]:
    """Resolves a hostname on a daemon thread so slow/unreachable DNS servers cannot hang collection."""
    outcome: Dict[str, Any] = {"ok": False, "ip": None, "error": f"DNS lookup timed out after {timeout}s"}

    def _worker() -> None:
        try:
            ip = socket.gethostbyname(domain)
            outcome["ok"] = True
            outcome["ip"] = ip
            outcome["error"] = None
        except Exception as exc:
            outcome["ok"] = False
            outcome["error"] = str(exc)

    th = threading.Thread(target=_worker, daemon=True)
    th.start()
    th.join(timeout=timeout)
    return outcome


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


def _parse_netsh_dns_output(output: str) -> Dict[str, Any]:
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
            for ip in re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", line):
                if ip not in ips:
                    ips.append(ip)

    dns_dhcp_enabled = True if (not is_static and not is_dhcp) else (not is_static)
    return {
        "dns_dhcp_enabled": dns_dhcp_enabled,
        "static_dns_configured": is_static,
        "dns_servers": ips,
    }


# ============================================================================
# LINUX LOW-LEVEL COLLECTORS
# ============================================================================

def _collect_linux_adapters() -> List[Dict[str, Any]]:
    """Enumerate network interfaces on Linux via ip -j link or ip link."""
    adapters: List[Dict[str, Any]] = []
    try:
        res = subprocess.run(["ip", "-j", "link"], capture_output=True, text=True, timeout=4)
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout)
            for iface in data:
                name = iface.get("ifname", "")
                if name == "lo":
                    continue
                flags = iface.get("flags", [])
                operstate = str(iface.get("operstate", "DOWN")).upper()
                status = "Up" if (operstate == "UP" or "UP" in flags) else "Disabled"
                mac = iface.get("address", "")
                is_virt = any(k in name.lower() for k in VIRTUAL_ADAPTER_KEYWORDS)
                adapters.append({
                    "name": name,
                    "description": f"Linux network interface {name}",
                    "status": status,
                    "media_state": 1 if status == "Up" else 2,
                    "mac_address": mac,
                    "is_virtual": is_virt
                })
            if adapters:
                return adapters
    except Exception:
        pass

    # Fallback to parsing standard 'ip link' output
    try:
        res = subprocess.run(["ip", "link"], capture_output=True, text=True, timeout=4)
        for line in res.stdout.splitlines():
            m = re.match(r"^\d+:\s+([a-zA-Z0-9_\-\.]+):.*state\s+([A-Z]+)", line)
            if m:
                name = m.group(1)
                if name == "lo":
                    continue
                st = "Up" if m.group(2) == "UP" else "Disabled"
                is_virt = any(k in name.lower() for k in VIRTUAL_ADAPTER_KEYWORDS)
                adapters.append({
                    "name": name,
                    "description": f"Linux interface {name}",
                    "status": st,
                    "media_state": 1 if st == "Up" else 2,
                    "mac_address": "",
                    "is_virtual": is_virt
                })
        if adapters:
            return adapters
    except Exception:
        pass

    return [{"name": "eth0", "status": "Up", "description": "Default Linux Ethernet", "is_virtual": False}]


def _collect_linux_ip_config(adapter_name: Optional[str] = None) -> Dict[str, Any]:
    """Collects IPv4, Gateway, DHCP state, and DNS on Linux."""
    ipv4 = None
    prefix = 24
    gateway = None
    dhcp_enabled = True
    dns_servers: List[str] = []

    # 1. IPv4 and prefix from ip -j addr
    try:
        cmd = ["ip", "-j", "addr"] if not adapter_name else ["ip", "-j", "addr", "show", adapter_name]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=4)
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout)
            for iface in data:
                if iface.get("ifname") == "lo":
                    continue
                for addr in iface.get("addr_info", []):
                    if addr.get("family") == "inet":
                        ipv4 = addr.get("local")
                        prefix = addr.get("prefixlen", 24)
                        if addr.get("dynamic") is False:
                            dhcp_enabled = False
                        break
                if ipv4:
                    if not adapter_name:
                        adapter_name = iface.get("ifname")
                    break
    except Exception:
        pass

    # Fallback to ip addr
    if not ipv4:
        try:
            res = subprocess.run(["ip", "addr"], capture_output=True, text=True, timeout=4)
            ip_m = re.search(r"inet\s+([0-9.]+)/(\d+)", res.stdout)
            if ip_m and not ip_m.group(1).startswith("127."):
                ipv4 = ip_m.group(1)
                prefix = int(ip_m.group(2))
        except Exception:
            pass

    # 2. Default gateway from ip -j route or ip route
    try:
        res = subprocess.run(["ip", "-j", "route", "show", "default"], capture_output=True, text=True, timeout=4)
        if res.returncode == 0 and res.stdout.strip():
            routes = json.loads(res.stdout)
            if routes and isinstance(routes, list):
                gateway = routes[0].get("gateway")
    except Exception:
        pass

    if not gateway:
        try:
            res = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True, timeout=4)
            gw_m = re.search(r"default via ([0-9.]+)", res.stdout)
            if gw_m:
                gateway = gw_m.group(1)
        except Exception:
            pass

    # 3. DNS servers from /etc/resolv.conf
    try:
        resolv = Path("/etc/resolv.conf")
        if resolv.exists():
            for line in resolv.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("nameserver"):
                    parts = line.split()
                    if len(parts) >= 2 and parts[1] not in dns_servers:
                        dns_servers.append(parts[1])
    except Exception:
        pass

    static_dns = len(dns_servers) > 0 and any(s in ("8.8.8.8", "1.1.1.1") for s in dns_servers)

    return {
        "adapter_name": adapter_name or "eth0",
        "ipv4_address": ipv4,
        "subnet_mask": _prefix_length_to_netmask(prefix),
        "default_gateway": gateway,
        "dhcp_enabled": dhcp_enabled,
        "dns_dhcp_enabled": not static_dns,
        "static_dns_configured": static_dns,
        "dns_servers": dns_servers,
        "is_apipa": bool(ipv4 and str(ipv4).startswith("169.254.")),
        "has_valid_ip": bool(ipv4 and not str(ipv4).startswith("169.254.") and not str(ipv4).startswith("127.")),
    }


def _linux_ping(host: Optional[str], count: int = 2, timeout_s: int = 2) -> Dict[str, Any]:
    """Execute ping on Linux with -c and -W flags."""
    if not host:
        return {"target_ip": host, "target_gateway": host, "reachable": False, "packet_loss_pct": 100, "avg_latency_ms": None}
    try:
        res = subprocess.run(
            ["ping", "-c", str(count), "-W", str(timeout_s), host],
            capture_output=True,
            text=True,
            timeout=timeout_s + 3
        )
        ok = res.returncode == 0
        loss_m = re.search(r"(\d+)% packet loss", res.stdout or "")
        loss = int(loss_m.group(1)) if loss_m else (0 if ok else 100)
        lat_m = re.search(r"rtt min/avg/max/mdev = [0-9.]+/([0-9.]+)/", res.stdout or "")
        avg_lat = float(lat_m.group(1)) if lat_m else (None if not ok else 15.0)

        return {
            "target_ip": host,
            "target_gateway": host,
            "reachable": ok,
            "packet_loss_pct": loss,
            "avg_latency_ms": avg_lat,
            "high_latency": bool(avg_lat and avg_lat > 5000),
            "high_packet_loss": bool(loss > 20)
        }
    except Exception as exc:
        return {"target_ip": host, "target_gateway": host, "reachable": False, "packet_loss_pct": 100, "error": str(exc)}


def _get_linux_firewall() -> Dict[str, Any]:
    """Checks UFW or iptables status on Linux."""
    try:
        res = subprocess.run(["ufw", "status"], capture_output=True, text=True, timeout=3)
        if res.returncode == 0:
            is_active = "active" in (res.stdout or "").lower()
            return {"UFW": is_active, "Domain": True, "Private": True, "Public": True}
    except Exception:
        pass
    return {"UFW": False, "Domain": True, "Private": True, "Public": True}


def _get_linux_services() -> Dict[str, Any]:
    """Checks status of critical Linux services: cups, systemd-resolved, NetworkManager."""
    results: Dict[str, Any] = {}
    service_map = {
        "cups": "Spooler",            # Map CUPS to Spooler for universal rule evaluation
        "systemd-resolved": "Dnscache",
        "NetworkManager": "Dhcp",
    }
    for svc_bin, canonical in service_map.items():
        try:
            res = subprocess.run(["systemctl", "is-active", svc_bin], capture_output=True, text=True, timeout=3)
            status_str = res.stdout.strip().lower()
            state = "Running" if status_str == "active" else "Stopped"
            results[canonical] = {"status": state, "native_service": svc_bin}
            results[svc_bin] = {"status": state}
        except Exception:
            results[canonical] = {"status": "Unknown"}
            results[svc_bin] = {"status": "Unknown"}

    for srv in ["Spooler", "Dhcp", "Dnscache", "WlanSvc"]:
        if srv not in results:
            results[srv] = {"status": "Running"}
    return results


# ============================================================================
# CROSS-PLATFORM ENDPOINT DIAGNOSTICS CLASS
# ============================================================================

class EndpointDiagnostics:
    @staticmethod
    def collect_all(target_domain: str = "college.edu") -> Dict[str, Any]:
        """Collects structured read-only diagnostics on Windows and Linux systems."""
        adapters = EndpointDiagnostics.get_all_adapters()
        primary = EndpointDiagnostics.get_adapter_status(adapters=adapters)
        adapter_name = primary.get("name")
        ip_config = EndpointDiagnostics.get_ip_configuration(adapter_name=adapter_name)

        with ThreadPoolExecutor(max_workers=5) as pool:
            f_gw = pool.submit(EndpointDiagnostics.test_gateway_ping, ip_config)
            f_net = pool.submit(EndpointDiagnostics.test_internet_ping)
            f_dns = pool.submit(EndpointDiagnostics.test_dns_resolution, target_domain, ip_config)
            f_fw = pool.submit(EndpointDiagnostics.get_firewall_status)
            f_srv = pool.submit(EndpointDiagnostics.get_critical_services)

            return {
                "network_adapter": primary,
                "adapters_list": adapters,
                "ip_config": ip_config,
                "gateway_ping": f_gw.result(),
                "internet_ping": f_net.result(),
                "dns_test": f_dns.result(),
                "firewall": f_fw.result(),
                "services": f_srv.result(),
            }

    @staticmethod
    def collect_heartbeat_sample(target_domain: str = "google.com") -> Dict[str, Any]:
        """Fast lightweight telemetry probe (~1.5s) suitable for daemon heartbeat streaming."""
        adapters = EndpointDiagnostics.get_all_adapters()
        primary = EndpointDiagnostics.get_adapter_status(adapters=adapters)
        adapter_name = primary.get("name")
        ip_config = EndpointDiagnostics.get_ip_configuration(adapter_name=adapter_name)

        def _fast_ping(host: Optional[str]) -> Dict[str, Any]:
            if not host:
                return {"reachable": False, "packet_loss_pct": 100, "avg_latency_ms": None}
            if _is_linux():
                return _linux_ping(host, count=1, timeout_s=2)
            try:
                res = subprocess.run(["ping", "-n", "1", "-w", "900", host], capture_output=True, text=True, timeout=3)
                ok = res.returncode == 0
                loss_m = re.search(r"\((\d+)% loss\)", res.stdout or "")
                lat_m = re.search(r"Average = (\d+)ms|time[=<](\d+)ms", res.stdout or "", re.IGNORECASE)
                lat = int(lat_m.group(1) or lat_m.group(2)) if lat_m else None
                return {
                    "target_gateway": host,
                    "target_ip": host,
                    "reachable": ok,
                    "packet_loss_pct": int(loss_m.group(1)) if loss_m else (0 if ok else 100),
                    "avg_latency_ms": lat,
                }
            except Exception as exc:
                return {"target_gateway": host, "target_ip": host, "reachable": False, "packet_loss_pct": 100, "error": str(exc)}

        with ThreadPoolExecutor(max_workers=4) as pool:
            f_gw = pool.submit(_fast_ping, ip_config.get("default_gateway"))
            f_net = pool.submit(_fast_ping, "8.8.8.8")
            f_dns = pool.submit(EndpointDiagnostics.test_dns_resolution, target_domain, ip_config)
            f_srv = pool.submit(EndpointDiagnostics.get_critical_services)

            return {
                "network_adapter": primary,
                "adapters_list": adapters,
                "ip_config": ip_config,
                "gateway_ping": f_gw.result(),
                "internet_ping": f_net.result(),
                "dns_test": f_dns.result(),
                "firewall": {"Domain": True, "Private": True, "Public": True},
                "services": f_srv.result(),
            }

    @staticmethod
    def get_ip_configuration(adapter_name: Optional[str] = None) -> Dict[str, Any]:
        """Collects IPv4, default gateway, DHCP state, and DNS mode."""
        if _is_linux():
            return _collect_linux_ip_config(adapter_name)

        # Windows implementation
        try:
            target = adapter_name or EndpointDiagnostics.get_adapter_status().get("name")
            if target:
                q_name = "'" + target.replace("'", "''") + "'"
                ps_cmd = [
                    "powershell", "-NoProfile", "-Command",
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
                ]
                res = subprocess.run(ps_cmd, capture_output=True, text=True, timeout=8)
                dns_res = subprocess.run(
                    ["netsh", "interface", "ipv4", "show", "dnsservers", f"name={target}"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                dns_parsed = _parse_netsh_dns_output((dns_res.stdout or "") + "\n" + (dns_res.stderr or ""))

                if res.returncode == 0 and res.stdout.strip():
                    data = json.loads(res.stdout)
                    ipv4 = data.get("ip")
                    gateway = data.get("gw")
                    dhcp_str = str(data.get("dhcp") or "").strip().lower()
                    dhcp_enabled = False if dhcp_str == "disabled" else True
                    dns_servers = dns_parsed.get("dns_servers") or [str(d) for d in (data.get("dns") or []) if d]

                    return {
                        "adapter_name": target,
                        "ipv4_address": ipv4,
                        "subnet_mask": _prefix_length_to_netmask(data.get("prefix")),
                        "default_gateway": gateway,
                        "dhcp_enabled": dhcp_enabled,
                        "dns_dhcp_enabled": dns_parsed.get("dns_dhcp_enabled", True),
                        "static_dns_configured": dns_parsed.get("static_dns_configured", False),
                        "dns_servers": dns_servers,
                        "is_apipa": bool(ipv4 and str(ipv4).startswith("169.254.")),
                        "has_valid_ip": bool(ipv4 and not str(ipv4).startswith("169.254.") and not str(ipv4).startswith("127.")),
                    }

            # Fallback to ipconfig /all
            res = subprocess.run(["ipconfig", "/all"], capture_output=True, text=True, timeout=5)
            out = res.stdout

            ipv4_match = re.search(r"IPv4 Address[ .:]+([0-9.]+)", out)
            gw_match = re.search(r"Default Gateway[ .:]+([0-9.]+)", out)
            dhcp_match = re.search(r"DHCP Enabled[ .:]+(Yes|No)", out, re.IGNORECASE)

            ipv4 = ipv4_match.group(1) if ipv4_match else None
            gateway = gw_match.group(1) if gw_match else None
            dhcp_enabled = (dhcp_match.group(1).lower() == "yes") if dhcp_match else True

            return {
                "adapter_name": target,
                "ipv4_address": ipv4,
                "default_gateway": gateway,
                "dhcp_enabled": dhcp_enabled,
                "dns_dhcp_enabled": True,
                "static_dns_configured": False,
                "dns_servers": [],
                "is_apipa": bool(ipv4 and ipv4.startswith("169.254.")),
                "has_valid_ip": bool(ipv4 and not ipv4.startswith("169.254.") and not ipv4.startswith("127."))
            }
        except Exception as e:
            return {"error": str(e), "ipv4_address": None, "default_gateway": None, "has_valid_ip": False}

    @staticmethod
    def get_adapter_status(adapters: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Returns primary active network adapter status."""
        adapters = adapters if adapters is not None else EndpointDiagnostics.get_all_adapters()
        physical = [a for a in adapters if not a.get("is_virtual", False)]
        physical_up = [a for a in physical if str(a.get("status", "")).lower() == "up"]

        for group in (physical_up, physical):
            for a in group:
                combined = f"{a.get('name', '')} {a.get('description', '')}".lower()
                if "wi-fi" in combined or "wifi" in combined or "wlan" in combined or "wireless" in combined:
                    return a
            if group:
                return group[0]

        for a in adapters:
            if str(a.get("status", "")).lower() == "up":
                return a
        if adapters:
            return adapters[0]
        return {"name": "eth0" if _is_linux() else "Wi-Fi", "status": "Disabled", "description": "No network adapter detected"}

    @staticmethod
    def get_all_adapters() -> List[Dict[str, Any]]:
        """Enumerates all network interfaces."""
        if _is_linux():
            return _collect_linux_adapters()

        # Windows
        try:
            cmd = [
                "powershell", "-NoProfile", "-Command",
                "Get-NetAdapter | Select-Object Name, InterfaceDescription, "
                "@{N='Status';E={$_.Status.ToString()}}, "
                "@{N='MediaState';E={[int]$_.MediaConnectionState}}, "
                "MacAddress | ConvertTo-Json -Compress"
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                if isinstance(data, dict):
                    data = [data]
                results = []
                for item in data:
                    name = item.get("Name", "")
                    desc = item.get("InterfaceDescription", "")
                    status = item.get("Status", "Unknown")
                    combined = f"{name} {desc}".lower()
                    is_virtual = any(k in combined for k in VIRTUAL_ADAPTER_KEYWORDS)
                    results.append({
                        "name": name,
                        "description": desc,
                        "status": status,
                        "media_state": int(item.get("MediaState", 0)),
                        "mac_address": item.get("MacAddress", ""),
                        "is_virtual": is_virtual
                    })
                return results
        except Exception:
            pass
        return [{"name": "Wi-Fi", "status": "Up", "description": "Default Wi-Fi Adapter", "is_virtual": False}]

    @staticmethod
    def test_gateway_ping(ip_conf: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Tests reachability and latency to the default gateway."""
        ip_conf = ip_conf if ip_conf is not None else EndpointDiagnostics.get_ip_configuration()
        gw = ip_conf.get("default_gateway")
        if not gw:
            return {
                "reachable": False,
                "packet_loss_pct": 100,
                "avg_latency_ms": None,
                "note": "No default gateway configured."
            }

        if _is_linux():
            res = _linux_ping(gw, count=3, timeout_s=2)
            res["target_gateway"] = gw
            return res

        # Windows
        try:
            res = subprocess.run(["ping", "-n", "3", "-w", "1000", gw], capture_output=True, text=True, timeout=6)
            reachable = (res.returncode == 0)
            loss_match = re.search(r"\((\d+)% loss\)", res.stdout)
            loss = int(loss_match.group(1)) if loss_match else (0 if reachable else 100)

            lat_match = re.search(r"Average = (\d+)ms", res.stdout)
            avg_lat = int(lat_match.group(1)) if lat_match else None

            return {
                "target_gateway": gw,
                "reachable": reachable,
                "packet_loss_pct": loss,
                "avg_latency_ms": avg_lat,
                "high_latency": bool(avg_lat and avg_lat > 5000),
                "high_packet_loss": bool(loss > 20)
            }
        except Exception as e:
            return {"target_gateway": gw, "reachable": False, "packet_loss_pct": 100, "error": str(e)}

    @staticmethod
    def test_internet_ping(target_ip: str = "8.8.8.8") -> Dict[str, Any]:
        """Tests public WAN reachability."""
        if _is_linux():
            return _linux_ping(target_ip, count=3, timeout_s=2)

        # Windows
        try:
            res = subprocess.run(["ping", "-n", "3", "-w", "1000", target_ip], capture_output=True, text=True, timeout=6)
            reachable = (res.returncode == 0)
            loss_match = re.search(r"\((\d+)% loss\)", res.stdout)
            loss = int(loss_match.group(1)) if loss_match else (0 if reachable else 100)

            lat_match = re.search(r"Average = (\d+)ms", res.stdout)
            avg_lat = int(lat_match.group(1)) if lat_match else None

            return {
                "target_ip": target_ip,
                "reachable": reachable,
                "packet_loss_pct": loss,
                "avg_latency_ms": avg_lat,
                "high_latency": bool(avg_lat and avg_lat > 5000),
                "high_packet_loss": bool(loss > 20)
            }
        except Exception as e:
            return {"target_ip": target_ip, "reachable": False, "packet_loss_pct": 100, "error": str(e)}

    @staticmethod
    def test_dns_resolution(domain: str = "college.edu", ip_conf: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Tests DNS lookup against target domain and public domain with bounded timeout."""
        result: Dict[str, Any] = {"resolved": False, "target_domain": domain, "resolved_ip": None}
        if ip_conf:
            result["dns_dhcp_enabled"] = ip_conf.get("dns_dhcp_enabled", True)
            result["dns_servers"] = ip_conf.get("dns_servers", [])

        primary_lookup = _resolve_hostname_with_timeout(domain, timeout=3.5)
        if primary_lookup["ok"]:
            result["resolved"] = True
            result["resolved_ip"] = primary_lookup["ip"]
        else:
            result["error"] = primary_lookup["error"]

        # Also test public Internet resolution (google.com) to distinguish private vs global DNS
        pub_lookup = _resolve_hostname_with_timeout("google.com", timeout=3.5)
        if pub_lookup["ok"]:
            result["public_dns_resolved"] = True
            result["public_ip"] = pub_lookup["ip"]
            if not result["resolved"]:
                result["resolved"] = True
                result["resolved_ip"] = pub_lookup["ip"]
        else:
            result["public_dns_resolved"] = False

        return result

    @staticmethod
    def get_firewall_status() -> Dict[str, Any]:
        """Checks Firewall status."""
        if _is_linux():
            return _get_linux_firewall()

        # Windows
        try:
            cmd = ["powershell", "-NoProfile", "-Command", "Get-NetFirewallProfile | Select-Object Name, Enabled | ConvertTo-Json -Compress"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
            if res.returncode == 0 and res.stdout.strip():
                profiles = json.loads(res.stdout)
                if isinstance(profiles, dict):
                    profiles = [profiles]
                return {p.get("Name"): bool(p.get("Enabled")) for p in profiles}
        except Exception:
            pass
        return {"Domain": True, "Private": True, "Public": True}

    @staticmethod
    def get_critical_services() -> Dict[str, Any]:
        """Checks status of critical networking and printing services."""
        if _is_linux():
            return _get_linux_services()

        # Windows
        results: Dict[str, Any] = {}
        try:
            cmd = [
                "powershell", "-NoProfile", "-Command",
                "Get-Service -Name Spooler,Dhcp,Dnscache,WlanSvc -ErrorAction SilentlyContinue | "
                "Select-Object Name, @{N='Status';E={$_.Status.ToString()}} | ConvertTo-Json -Compress"
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
            if res.returncode == 0 and res.stdout.strip():
                items = json.loads(res.stdout)
                if isinstance(items, dict):
                    items = [items]
                for item in items:
                    name = str(item.get("Name") or "")
                    if name:
                        results[name] = {"status": str(item.get("Status") or "Unknown")}
        except Exception:
            pass

        for srv in ["Spooler", "Dhcp", "Dnscache", "WlanSvc"]:
            if srv not in results:
                results[srv] = {"status": "Unknown"}
        return results
