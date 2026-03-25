"""MCP server registry primitives for the provider runtime."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

MCPTransport = str

if TYPE_CHECKING:
    from copilot.types import MCPLocalServerConfig, MCPRemoteServerConfig

    type MCPSDKServerConfig = MCPLocalServerConfig | MCPRemoteServerConfig


class MCPServerDefinition(BaseModel):
    """Describe one MCP server that the provider may mount into a session.

    Attributes:
        name: Stable provider-owned MCP server identifier.
        transport: Mount style used to connect to the MCP server.
        command: Executable used for ``stdio`` transports.
        args: Command-line arguments forwarded to ``command``.
        env: Extra environment variables passed to the launched process.
        headers: Optional HTTP headers for remote MCP mounts.
        tools: Optional allow-list of tools exposed through this server mount.
        cwd: Optional working directory for ``stdio`` transports.
        timeout_seconds: Optional startup/request timeout forwarded to the SDK.
        url: Base URL used for HTTP-backed MCP transports.

    """

    model_config = ConfigDict(extra='forbid', frozen=True)

    name: str = Field(min_length=1)
    transport: MCPTransport = 'stdio'
    command: str | None = None
    args: tuple[str, ...] = ()
    env: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    tools: tuple[str, ...] = ()
    cwd: str | None = None
    timeout_seconds: int | None = None
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
            if self.headers:
                msg = 'stdio MCP servers must not define HTTP headers'
                raise ValueError(msg)
        elif self.transport == 'http':
            if self.url is None:
                msg = 'http MCP servers must define a url'
                raise ValueError(msg)
            if self.command is not None:
                msg = 'http MCP servers must not define a command'
                raise ValueError(msg)
            if self.cwd is not None:
                msg = 'http MCP servers must not define a cwd'
                raise ValueError(msg)
        else:
            msg = f'Unsupported MCP transport "{self.transport}"'
            raise ValueError(msg)

        return self

    def to_sdk_config(self) -> MCPLocalServerConfig | MCPRemoteServerConfig:
        """Translate this server definition into the SDK's session config shape.

        Returns:
            A typed dictionary matching the ``copilot-sdk`` ``mcp_servers``
            argument expected by ``create_session()`` and ``resume_session()``.

        """
        if self.transport == 'stdio':
            config: dict[str, object] = {
                'command': self.command,
                'args': list(self.args),
                'tools': list(self.tools),
            }
            if self.env:
                config['env'] = self.env
            if self.cwd is not None:
                config['cwd'] = self.cwd
            if self.timeout_seconds is not None:
                config['timeout'] = self.timeout_seconds

            return cast('MCPLocalServerConfig', config)

        config: dict[str, object] = {
            'type': self.transport,
            'url': self.url,
            'tools': list(self.tools),
        }
        if self.headers:
            config['headers'] = self.headers
        if self.timeout_seconds is not None:
            config['timeout'] = self.timeout_seconds

        return cast('MCPRemoteServerConfig', config)


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

    def sdk_server_configs(
        self,
    ) -> dict[str, MCPLocalServerConfig | MCPRemoteServerConfig]:
        """Return the SDK-ready ``mcp_servers`` mapping for every registered server.

        Returns:
            A dictionary keyed by server name where each value matches the
            ``copilot-sdk`` local or remote MCP server configuration shape.

        """
        return {
            server.name: server.to_sdk_config() for server in self._servers.values()
        }
