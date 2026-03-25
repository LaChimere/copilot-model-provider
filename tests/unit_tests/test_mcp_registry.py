"""Unit tests for MCP registry primitives."""

from __future__ import annotations

import pytest

from copilot_model_provider.tools import MCPRegistry, MCPServerDefinition


def test_mcp_registry_preserves_registration_order() -> None:
    """Verify that registered MCP servers are listed in stable insertion order."""
    registry = MCPRegistry()
    filesystem_server = MCPServerDefinition(
        name='filesystem',
        transport='stdio',
        command='node',
        args=('dist/server.js',),
    )
    docs_server = MCPServerDefinition(
        name='docs-api',
        transport='http',
        url='http://localhost:8123/mcp',
    )

    registry.register(filesystem_server)
    registry.register(docs_server)

    assert registry.list_servers() == (filesystem_server, docs_server)
    assert registry.get_server('filesystem') == filesystem_server


def test_mcp_registry_rejects_duplicate_names() -> None:
    """Verify that duplicate MCP server registrations raise a descriptive error."""
    registry = MCPRegistry()
    registry.register(
        MCPServerDefinition(
            name='filesystem',
            transport='stdio',
            command='node',
            args=('dist/server.js',),
        )
    )

    with pytest.raises(ValueError, match='already registered'):
        registry.register(
            MCPServerDefinition(
                name='filesystem',
                transport='stdio',
                command='node',
            )
        )


def test_mcp_server_definition_requires_transport_specific_fields() -> None:
    """Verify that each MCP transport enforces the correct configuration shape."""
    with pytest.raises(ValueError, match='must define a command'):
        MCPServerDefinition(name='filesystem', transport='stdio')

    with pytest.raises(ValueError, match='must define a url'):
        MCPServerDefinition(name='docs-api', transport='http')
