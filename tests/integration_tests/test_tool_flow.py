"""Focused integration tests for server-approved tool mounting."""

from __future__ import annotations

from typing import cast

import pytest
from copilot.generated.session_events import PermissionRequest
from copilot.types import ToolInvocation, ToolResult

from copilot_model_provider.core.policies import PolicyEngine
from copilot_model_provider.runtimes.copilot import (
    CopilotClientLike,
    CopilotRuntimeAdapter,
)
from copilot_model_provider.tools import ToolDefinition, ToolRegistry
from tests.integration_tests.harness import build_async_client
from tests.unit_tests.test_copilot_runtime import (
    _FakeClient,
    _FakeEvent,
    _FakeEventData,
    _FakeSession,
)


@pytest.mark.asyncio
async def test_http_chat_route_mounts_server_approved_tools_into_runtime_sessions() -> (
    None
):
    """Verify that the HTTP chat route mounts server-approved tools into the runtime."""

    def _handler(invocation: ToolInvocation) -> ToolResult:
        """Return a deterministic tool result for the integration test."""
        return ToolResult(text_result_for_llm=f'docs:{invocation.arguments["query"]}')

    session = _FakeSession(
        event=_FakeEvent(
            data=_FakeEventData(
                content='Tool-assisted reply.',
                message_id='chatcmpl-tool',
            )
        )
    )
    client = _FakeClient(session=session)
    tool_registry = ToolRegistry(
        (
            ToolDefinition(
                name='search-docs',
                description='Search provider documentation.',
                input_schema={'type': 'object'},
                handler=_handler,
            ),
        )
    )
    runtime_adapter = CopilotRuntimeAdapter(
        client_factory=lambda: cast('CopilotClientLike', client),
        tool_registry=tool_registry,
        policy_engine=PolicyEngine(tool_registry=tool_registry),
    )

    async with build_async_client(runtime_adapter=runtime_adapter) as http_client:
        response = await http_client.post(
            '/v1/chat/completions',
            json={
                'model': 'default',
                'messages': [{'role': 'user', 'content': 'Find Step 4 docs'}],
            },
        )

    create_session_call = client.create_session_calls[0]
    tools = create_session_call['tools']
    permission_handler = create_session_call['on_permission_request']

    assert response.status_code == 200
    assert tools is not None
    assert len(tools) == 1
    assert tools[0].name == 'search-docs'

    tool_result = tools[0].handler(
        ToolInvocation(
            session_id='session-1',
            tool_call_id='tool-call-1',
            tool_name='search-docs',
            arguments={'query': 'step4'},
        )
    )
    assert tool_result.text_result_for_llm == 'docs:step4'

    permission_result = permission_handler(
        PermissionRequest.from_dict({'kind': 'custom-tool', 'toolName': 'search-docs'}),
        {},
    )
    assert permission_result.kind == 'approved'
