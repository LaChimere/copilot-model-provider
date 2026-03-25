"""Focused integration tests for MCP session mounting."""

from __future__ import annotations

from typing import cast

import pytest

from copilot_model_provider.runtimes.copilot import (
    CopilotClientLike,
    CopilotRuntimeAdapter,
)
from copilot_model_provider.tools import MCPRegistry, MCPServerDefinition
from tests.integration_tests.harness import build_async_client
from tests.unit_tests.test_copilot_runtime import (
    _FakeClient,
    _FakeEvent,
    _FakeEventData,
    _FakeSession,
)


@pytest.mark.asyncio
async def test_http_chat_route_forwards_mcp_mounts_into_runtime_sessions() -> None:
    """Verify that the HTTP chat route uses runtime sessions with configured MCP mounts."""
    session = _FakeSession(
        event=_FakeEvent(
            data=_FakeEventData(
                content='Hi from Copilot',
                message_id='chatcmpl-mcp',
            )
        )
    )
    client = _FakeClient(session=session)
    runtime_adapter = CopilotRuntimeAdapter(
        client_factory=lambda: cast('CopilotClientLike', client),
        mcp_registry=MCPRegistry(
            (
                MCPServerDefinition(
                    name='docs-api',
                    transport='http',
                    url='http://localhost:8123/mcp',
                    tools=('search_docs',),
                ),
            )
        ),
    )

    async with build_async_client(runtime_adapter=runtime_adapter) as http_client:
        response = await http_client.post(
            '/v1/chat/completions',
            json={
                'model': 'default',
                'messages': [{'role': 'user', 'content': 'Ping'}],
            },
        )

    assert response.status_code == 200
    assert client.create_session_calls[0]['mcp_servers'] == {
        'docs-api': {
            'type': 'http',
            'url': 'http://localhost:8123/mcp',
            'tools': ['search_docs'],
        }
    }
