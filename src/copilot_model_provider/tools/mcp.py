"""MCP server registry primitives for the provider runtime."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

MCPTransport = str


class MCPServerDefinition(BaseModel):
    """Describe one MCP server that the provider may mount into a session.

    Attributes:
        name: Stable provider-owned MCP server identifier.
        transport: Mount style used to connect to the MCP server.
        command: Executable used for ``stdio`` transports.
        args: Command-line arguments forwarded to ``command``.
        env: Extra environment variables passed to the launched process.
        url: Base URL used for HTTP-backed MCP transports.

    """

    model_config = ConfigDict(extra='forbid', frozen=True)

    name: str = Field(min_length=1)
    transport: MCPTransport = 'stdio'
    command: str | None = None
    args: tuple[str, ...] = ()
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None

    @model_validator(mode='after')
    def _validate_transport_shape(self) -> MCPServerDefinition:
        """Ensure the selected transport has the required connection fields."""
        if self.transport == 'stdio':
            if self.command is None:
                msg = 'stdio MCP servers must define a command'
                raise ValueError(msg)
            if self.url is not None:
                msg = 'stdio MCP servers must not define a url'
                raise ValueError(msg)
        elif self.transport == 'http':
            if self.url is None:
                msg = 'http MCP servers must define a url'
                raise ValueError(msg)
            if self.command is not None:
                msg = 'http MCP servers must not define a command'
                raise ValueError(msg)
        else:
            msg = f'Unsupported MCP transport "{self.transport}"'
            raise ValueError(msg)

        return self


class MCPRegistry:
    """Store the stable set of MCP server mounts known to the provider.

    The registry owns declaration and lookup only. A later behavioral commit
    can translate these definitions into Copilot SDK session arguments without
    changing the underlying storage or validation surface.

    """

    def __init__(self, servers: tuple[MCPServerDefinition, ...] = ()) -> None:
        """Initialize the registry with any predeclared server definitions.

        Args:
            servers: Optional tuple of MCP server definitions to preload while
                preserving registration order.

        """
        self._servers: dict[str, MCPServerDefinition] = {}
        for server in servers:
            self.register(server)

    def register(self, server: MCPServerDefinition) -> MCPServerDefinition:
        """Register ``server`` and return the stored definition.

        Args:
            server: The MCP server definition to store.

        Returns:
            The same validated ``MCPServerDefinition`` instance after it has
            been added to the registry.

        Raises:
            ValueError: If another server with the same name is already present.

        """
        if server.name in self._servers:
            msg = f'MCP server "{server.name}" is already registered'
            raise ValueError(msg)

        self._servers[server.name] = server
        return server

    def get_server(self, name: str) -> MCPServerDefinition | None:
        """Return the registered MCP server named ``name`` when one exists.

        Args:
            name: Stable MCP server identifier to look up.

        Returns:
            The matching ``MCPServerDefinition`` when present, otherwise
            ``None``.

        """
        return self._servers.get(name)

    def list_servers(self) -> tuple[MCPServerDefinition, ...]:
        """Return every registered MCP server in stable registration order.

        Returns:
            A tuple of MCP server definitions suitable for deterministic wiring
            and test assertions.

        """
        return tuple(self._servers.values())
