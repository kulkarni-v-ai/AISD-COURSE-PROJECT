from typing import Dict, Any, Tuple, Optional
from app.core.config import settings
from app.remediation.registry import get_tool, ToolDefinition


class PolicyEngine:
    def __init__(self):
        self.mock_mode = settings.REMEDIATION_MOCK_MODE
        self.require_approval_r2 = settings.REQUIRE_APPROVAL_FOR_R2
        self.require_approval_r3 = settings.REQUIRE_APPROVAL_FOR_R3

    def evaluate_plan_creation(
        self,
        tool_id: str,
        arguments: Dict[str, Any],
        user_role: str
    ) -> Tuple[bool, str, Optional[ToolDefinition], bool]:
        """
        Validates whether a tool can be planned.
        Returns: (is_allowed, reason, tool_def, approval_required)
        """
        tool = get_tool(tool_id)
        if not tool:
            return False, f"Tool '{tool_id}' is not in the predefined allowed tool registry.", None, False

        # Validate arguments schema (simple type & enum checks)
        schema = tool.parameters_schema
        for param, spec in schema.items():
            if spec.get("required", False) and param not in arguments:
                return False, f"Missing required parameter '{param}' for tool '{tool_id}'.", tool, False
            if "enum" in spec and param in arguments:
                val = arguments[param]
                if val not in spec["enum"]:
                    return False, f"Value '{val}' for parameter '{param}' is not allowed. Allowed: {spec['enum']}", tool, False

        # Check risk level and approval requirement
        approval_required = False
        if tool.risk_level == "R2" and self.require_approval_r2:
            approval_required = True
        elif tool.risk_level == "R3" and self.require_approval_r3:
            approval_required = True
        elif tool.requires_approval:
            approval_required = True

        return True, "Plan complies with remediation safety policy.", tool, approval_required

    def can_execute(
        self,
        tool_id: str,
        approval_status: Optional[str],
        approval_required: bool,
        user_role: str
    ) -> Tuple[bool, str]:
        """
        Validates whether an action is authorized to execute.
        """
        tool = get_tool(tool_id)
        if not tool:
            return False, f"Unknown tool '{tool_id}'."

        if approval_required:
            if approval_status != "APPROVED":
                return False, f"Execution denied: Tool '{tool_id}' (Risk: {tool.risk_level}) requires technician approval. Current approval status: {approval_status or 'PENDING'}."

        return True, "Execution authorized by policy."


policy_engine = PolicyEngine()
