"""Policy primitives for approving tool and MCP-related runtime requests."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from copilot_model_provider.tools import ToolRegistry


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    """Describe whether a runtime permission request should be approved."""

    allowed: bool
    reason: str


class ToolPermissionPolicy(BaseModel):
    """Define the server-side rules for automatically approved tool requests.

    Attributes:
        allow_server_approved_tools: Enables automatic approval for registry
            entries marked ``server-approved``.
        allowed_tool_names: Explicit allow-list that can approve tools even when
            they are not marked ``server-approved`` in the registry.
        denied_tool_names: Explicit deny-list that always wins over other rules.
        builtin_tool_policy: Default policy for SDK built-in tools when a later
            runtime commit surfaces those names through permission requests.
        allowed_builtin_tool_names: Stable built-in tool names allowed when
            ``builtin_tool_policy`` is ``allow-listed``.

    """

    model_config = ConfigDict(extra='forbid', frozen=True)

    allow_server_approved_tools: bool = True
    allowed_tool_names: frozenset[str] = Field(default_factory=frozenset)
    denied_tool_names: frozenset[str] = Field(default_factory=frozenset)
    builtin_tool_policy: str = 'deny-all'
    allowed_builtin_tool_names: frozenset[str] = Field(default_factory=frozenset)


class PolicyEngine:
    """Evaluate whether tool-related permission requests should be approved.

    The MVP keeps policy evaluation deterministic and explicit. The engine
    consumes a registry plus a declarative ``ToolPermissionPolicy`` so runtime
    code can ask one narrow question — whether a named tool should be allowed —
    without hardcoding policy decisions into the transport layer.

    """

    def __init__(
        self,
        *,
        tool_registry: ToolRegistry | None = None,
        tool_policy: ToolPermissionPolicy | None = None,
    ) -> None:
        """Initialize the engine with optional registry and policy inputs.

        Args:
            tool_registry: Registry used to resolve provider-known tool
                metadata during policy checks.
            tool_policy: Declarative approval policy; when omitted, the engine
                uses the repository's MVP defaults.

        """
        self._tool_registry = tool_registry or ToolRegistry()
        self._tool_policy = tool_policy or ToolPermissionPolicy()

    def evaluate_tool_permission(
        self,
        tool_name: str,
        *,
        is_builtin: bool = False,
    ) -> PermissionDecision:
        """Evaluate whether the named tool should be approved automatically.

        Args:
            tool_name: Stable tool name to inspect.
            is_builtin: Marks whether the request targets a Copilot SDK
                built-in tool rather than a registered custom tool.

        Returns:
            A ``PermissionDecision`` describing whether the request should be
            allowed and the primary rule that produced that outcome.

        """
        if tool_name in self._tool_policy.denied_tool_names:
            return PermissionDecision(
                allowed=False,
                reason='tool is explicitly denied by policy',
            )

        if tool_name in self._tool_policy.allowed_tool_names:
            return PermissionDecision(
                allowed=True,
                reason='tool is explicitly allowed by policy',
            )

        if is_builtin:
            return self._evaluate_builtin_tool(tool_name)

        tool = self._tool_registry.get_tool(tool_name)
        if tool is None:
            return PermissionDecision(
                allowed=False,
                reason='tool is not registered',
            )

        if (
            self._tool_policy.allow_server_approved_tools
            and tool.permission_mode == 'server-approved'
        ):
            return PermissionDecision(
                allowed=True,
                reason='tool is marked server-approved in the registry',
            )

        return PermissionDecision(
            allowed=False,
            reason='tool requires an explicit allow rule',
        )

    def can_approve_tool(self, tool_name: str, *, is_builtin: bool = False) -> bool:
        """Return whether the named tool can be approved automatically.

        Args:
            tool_name: Stable tool identifier to inspect.
            is_builtin: Marks whether the request targets a Copilot SDK
                built-in tool.

        Returns:
            ``True`` when the current engine configuration allows the tool,
            otherwise ``False``.

        """
        return self.evaluate_tool_permission(
            tool_name,
            is_builtin=is_builtin,
        ).allowed

    def _evaluate_builtin_tool(self, tool_name: str) -> PermissionDecision:
        """Evaluate approval for a built-in SDK tool."""
        if self._tool_policy.builtin_tool_policy == 'allow-all':
            return PermissionDecision(
                allowed=True,
                reason='built-in tool policy allows every built-in tool',
            )

        if (
            self._tool_policy.builtin_tool_policy == 'allow-listed'
            and tool_name in self._tool_policy.allowed_builtin_tool_names
        ):
            return PermissionDecision(
                allowed=True,
                reason='built-in tool is present in the allow list',
            )

        return PermissionDecision(
            allowed=False,
            reason='built-in tool is denied by policy',
        )
