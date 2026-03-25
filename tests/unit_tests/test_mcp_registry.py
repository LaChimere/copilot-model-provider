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
        tools=('read_file',),
    )
    docs_server = MCPServerDefinition(
        name='docs-api',
        transport='http',
        url='http://localhost:8123/mcp',
        headers={'Authorization': 'Bearer token'},
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


def test_mcp_registry_builds_sdk_server_configs() -> None:
    """Verify that MCP registry entries translate into SDK session config payloads."""
    registry = MCPRegistry(
        (
            MCPServerDefinition(
                name='filesystem',
                transport='stdio',
                command='node',
                args=('dist/server.js',),
                env={'NODE_ENV': 'test'},
                tools=('read_file',),
                cwd='/workspace',
                timeout_seconds=30,
            ),
            MCPServerDefinition(
                name='docs-api',
                transport='http',
                url='http://localhost:8123/mcp',
                headers={'Authorization': 'Bearer token'},
                tools=('search_docs',),
                timeout_seconds=45,
            ),
        )
    )

    assert registry.sdk_server_configs() == {
        'filesystem': {
            'command': 'node',
            'args': ['dist/server.js'],
            'env': {'NODE_ENV': 'test'},
            'tools': ['read_file'],
            'cwd': '/workspace',
            'timeout': 30,
        },
        'docs-api': {
            'type': 'http',
            'url': 'http://localhost:8123/mcp',
            'headers': {'Authorization': 'Bearer token'},
            'tools': ['search_docs'],
            'timeout': 45,
        },
    }
