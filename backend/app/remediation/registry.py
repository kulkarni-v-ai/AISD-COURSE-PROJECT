from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field


class ToolDefinition(BaseModel):
    tool_id: str
    name: str
    description: str
    risk_level: str  # R0: Read-only, R1: Low impact, R2: Disruptive/reversible, R3: High risk
    requires_approval: bool
    allowed_roles: List[str]  # student, technician, admin, agent
    parameters_schema: Dict[str, Any]
    verification_type: str
    default_timeout_seconds: int = 15


# Allowlisted Remediation & Diagnostic Tools
TOOL_REGISTRY: Dict[str, ToolDefinition] = {
    "collect_network_status": ToolDefinition(
        tool_id="collect_network_status",
        name="Collect Network Status",
        description="Inspects active network adapters, IP configuration, gateway, and DNS configuration.",
        risk_level="R0",
        requires_approval=False,
        allowed_roles=["student", "technician", "admin", "agent"],
        parameters_schema={},
        verification_type="none",
        default_timeout_seconds=10
    ),
    "test_gateway": ToolDefinition(
        tool_id="test_gateway",
        name="Test Gateway Reachability",
        description="Sends ICMP ping probes to the default gateway.",
        risk_level="R1",
        requires_approval=False,
        allowed_roles=["student", "technician", "admin", "agent"],
        parameters_schema={
            "gateway_ip": {"type": "string", "required": False},
            "count": {"type": "integer", "default": 4}
        },
        verification_type="gateway_ping",
        default_timeout_seconds=10
    ),
    "test_dns": ToolDefinition(
        tool_id="test_dns",
        name="Test DNS Resolution",
        description="Tests name resolution for configured domains against local/campus DNS servers.",
        risk_level="R1",
        requires_approval=False,
        allowed_roles=["student", "technician", "admin", "agent"],
        parameters_schema={
            "domains": {"type": "array", "items": "string", "default": ["college.edu", "google.com"]}
        },
        verification_type="dns_resolve",
        default_timeout_seconds=10
    ),
    "renew_dhcp": ToolDefinition(
        tool_id="renew_dhcp",
        name="Renew DHCP Lease (Reset Static IP/DNS)",
        description="Resets static IPv4/DNS settings to automatic DHCP if configured manually (netsh source=dhcp) and renews the DHCP lease on the active physical adapter.",
        risk_level="R2",
        requires_approval=True,  # Approval gated by policy
        allowed_roles=["technician", "admin"],
        parameters_schema={
            "adapter_name": {"type": "string", "default": "auto"}
        },
        verification_type="ip_validity",
        default_timeout_seconds=30
    ),
    "flush_dns_cache": ToolDefinition(
        tool_id="flush_dns_cache",
        name="Reset Static DNS & Flush DNS Cache",
        description="Resets manually configured static DNS servers back to automatic DHCP if set, flushes the Windows DNS resolver cache (DnsFlushResolverCache), and re-registers DNS.",
        risk_level="R1",
        requires_approval=False,
        allowed_roles=["student", "technician", "admin", "agent"],
        parameters_schema={
            "adapter_name": {"type": "string", "default": "auto"}
        },
        verification_type="dns_resolve",
        default_timeout_seconds=20
    ),
    "enable_adapter": ToolDefinition(
        tool_id="enable_adapter",
        name="Enable Network Adapter",
        description="Enables a disabled network adapter interface.",
        risk_level="R2",
        requires_approval=True,
        allowed_roles=["technician", "admin"],
        parameters_schema={
            "adapter_name": {"type": "string", "required": True}
        },
        verification_type="adapter_status",
        default_timeout_seconds=15
    ),
    "get_service_status": ToolDefinition(
        tool_id="get_service_status",
        name="Get Windows Service Status",
        description="Checks the current state of a registered Windows service (e.g., Spooler, Dhcp).",
        risk_level="R0",
        requires_approval=False,
        allowed_roles=["student", "technician", "admin", "agent"],
        parameters_schema={
            "service_name": {"type": "string", "required": True}
        },
        verification_type="none",
        default_timeout_seconds=5
    ),
    "restart_approved_service": ToolDefinition(
        tool_id="restart_approved_service",
        name="Restart Approved Service",
        description="Restarts an approved Windows service (Spooler, Dhcp, Dnscache). Disallowed for arbitrary services.",
        risk_level="R2",
        requires_approval=True,
        allowed_roles=["technician", "admin"],
        parameters_schema={
            "service_name": {"type": "string", "enum": ["Spooler", "Dhcp", "Dnscache"], "required": True}
        },
        verification_type="service_running",
        default_timeout_seconds=15
    ),
    "verify_network_connectivity": ToolDefinition(
        tool_id="verify_network_connectivity",
        name="Verify Full Network Connectivity",
        description="Performs end-to-end verification: IP address, Gateway ping, DNS resolution, and HTTP probe.",
        risk_level="R0",
        requires_approval=False,
        allowed_roles=["student", "technician", "admin", "agent"],
        parameters_schema={},
        verification_type="full_network",
        default_timeout_seconds=15
    )
}


def get_tool(tool_id: str) -> Optional[ToolDefinition]:
    return TOOL_REGISTRY.get(tool_id)


def is_tool_registered(tool_id: str) -> bool:
    return tool_id in TOOL_REGISTRY
