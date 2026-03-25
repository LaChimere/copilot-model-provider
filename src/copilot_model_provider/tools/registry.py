"""Tool registry primitives for provider-owned and client-declared tools."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

ToolSource = str
ToolPermissionMode = str


class ToolDefinition(BaseModel):
    """Describe one tool that can be exposed through the provider runtime.

    Attributes:
        name: Stable tool identifier forwarded to clients and the underlying
            runtime integration.
        description: Human-readable summary of the tool's behavior.
        input_schema: JSON-schema-like shape for the tool input payload.
        source: Declares whether the tool originates from the client, the
            provider service, or an MCP mount.
        permission_mode: Declares whether the tool can be approved
            automatically by server policy or requires an explicit allow rule.
        override_builtin: Marks whether the tool is intended to replace a
            similarly named built-in capability.

    """

    model_config = ConfigDict(extra='forbid', frozen=True)

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    input_schema: dict[str, object] = Field(default_factory=dict)
    source: ToolSource = 'server'
    permission_mode: ToolPermissionMode = 'server-approved'
    override_builtin: bool = False


class ToolRegistry:
    """Store the stable set of tool definitions known to the provider.

    The registry is intentionally lightweight in the MVP: it provides a stable
    lookup surface for app wiring and policy evaluation without yet taking on
    execution concerns. Later commits can reuse the same structure when they
    bind real tool execution into the Copilot runtime adapter.

    """

    def __init__(self, tools: tuple[ToolDefinition, ...] = ()) -> None:
        """Initialize the registry with any pre-declared tools.

        Args:
            tools: Optional tuple of existing tool definitions to preload into
                the registry while preserving their declared order.

        """
        self._tools: dict[str, ToolDefinition] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: ToolDefinition) -> ToolDefinition:
        """Register ``tool`` and return the stored definition.

        Args:
            tool: The tool definition to store.

        Returns:
            The same validated ``ToolDefinition`` instance after it has been
            added to the registry.

        Raises:
            ValueError: If another tool with the same name is already present.

        """
        if tool.name in self._tools:
            msg = f'Tool "{tool.name}" is already registered'
            raise ValueError(msg)

        self._tools[tool.name] = tool
        return tool

    def get_tool(self, name: str) -> ToolDefinition | None:
        """Return the registered tool named ``name`` when one exists.

        Args:
            name: Stable tool identifier to look up.

        Returns:
            The matching ``ToolDefinition`` when present, otherwise ``None``.

        """
        return self._tools.get(name)

    def list_tools(self) -> tuple[ToolDefinition, ...]:
        """Return every registered tool in stable registration order.

        Returns:
            A tuple of registered tools suitable for deterministic app wiring,
            policy evaluation, and test assertions.

        """
        return tuple(self._tools.values())

    def list_server_approved_tools(self) -> tuple[ToolDefinition, ...]:
        """Return only tools that the server may approve automatically.

        Returns:
            A tuple containing the subset of registered tools whose
            ``permission_mode`` is ``server-approved``.

        """
        return tuple(
            tool
            for tool in self._tools.values()
            if tool.permission_mode == 'server-approved'
        )

    def approved_tool_names(self) -> tuple[str, ...]:
        """Return stable names for every automatically approved tool.

        Returns:
            A tuple of tool names in registration order for tools whose
            ``permission_mode`` is ``server-approved``.

        """
        return tuple(tool.name for tool in self.list_server_approved_tools())
