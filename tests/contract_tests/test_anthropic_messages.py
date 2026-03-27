"""Contract tests for the Anthropic-compatible Messages endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast, override

import pytest
from copilot.generated.session_events import SessionEvent

from copilot_model_provider.api.anthropic.protocol import (
    estimate_anthropic_input_tokens,
)
from copilot_model_provider.config import ProviderSettings
from copilot_model_provider.core.models import (
    AnthropicMessagesCountTokensRequest,
    CanonicalChatRequest,
    ResolvedRoute,
    RuntimeCompletion,
    RuntimeHealth,
)
from copilot_model_provider.runtimes.protocols import (
    RuntimeEventStream,
    RuntimeProtocol,
)
from tests.harness import build_async_client

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class _FakeAnthropicRuntime(RuntimeProtocol):
    """Deterministic runtime used by Anthropic HTTP contract tests."""

    supported_model_ids = ('claude-sonnet-4-20250514', 'claude-haiku-3.5')

    def __init__(self) -> None:
        """Initialize the fake runtime state."""
        self.last_request: CanonicalChatRequest | None = None

    @property
    @override
    def runtime_name(self) -> str:
        """Return the stable runtime identifier used by the fake runtime."""
        return 'copilot'

    @override
    def default_route(self) -> ResolvedRoute:
        """Return a default stateless route for the fake runtime."""
        return ResolvedRoute(runtime='copilot')

    @override
    async def check_health(self) -> RuntimeHealth:
        """Return a healthy fake runtime payload for internal diagnostics."""
        return RuntimeHealth(runtime='copilot', available=True, detail='ok')

    @override
    async def list_model_ids(
        self,
        *,
        runtime_auth_token: str | None = None,
    ) -> tuple[str, ...]:
        """Return a deterministic live-model snapshot for the fake runtime."""
        del runtime_auth_token
        return self.supported_model_ids

    @override
    async def complete_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeCompletion:
        """Return a deterministic non-streaming completion for HTTP tests."""
        del route
        self.last_request = request
        return RuntimeCompletion(
            output_text='HELLO',
            provider_response_id='anthropic-contract',
            prompt_tokens=11,
            completion_tokens=2,
        )

    @override
    async def stream_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeEventStream:
        """Return a deterministic text stream for Anthropic SSE tests."""
        del route
        self.last_request = request

        async def _events() -> AsyncIterator[SessionEvent]:
            """Yield a minimal assistant streaming turn for contract validation."""
            for event in (
                SessionEvent.from_dict(
                    {
                        'id': '10000000-0000-0000-0000-000000000001',
                        'timestamp': '2025-01-01T00:00:00Z',
                        'type': 'assistant.message_delta',
                        'data': {'deltaContent': 'HEL'},
                    }
                ),
                SessionEvent.from_dict(
                    {
                        'id': '10000000-0000-0000-0000-000000000002',
                        'timestamp': '2025-01-01T00:00:00Z',
                        'type': 'assistant.message_delta',
                        'data': {'deltaContent': 'LO'},
                    }
                ),
                SessionEvent.from_dict(
                    {
                        'id': '10000000-0000-0000-0000-000000000003',
                        'timestamp': '2025-01-01T00:00:00Z',
                        'type': 'assistant.turn_end',
                        'data': {'reason': 'stop'},
                    }
                ),
            ):
                yield event

        return RuntimeEventStream(session_id=None, events=_events())


@pytest.mark.asyncio
async def test_post_messages_returns_anthropic_compatible_payload() -> None:
    """Verify that the route returns the expected non-streaming Anthropic payload."""
    runtime = _FakeAnthropicRuntime()
    request_body: dict[str, object] = {
        'model': 'claude-sonnet-4-20250514',
        'max_tokens': 128,
        'system': [{'type': 'text', 'text': 'You are terse.'}],
        'messages': [
            {
                'role': 'user',
                'content': [{'type': 'text', 'text': 'Reply with HELLO.'}],
            }
        ],
        'tools': [
            {
                'name': 'read_file',
                'description': 'Read a file.',
                'input_schema': {'type': 'object'},
            }
        ],
    }
    async with build_async_client(runtime=runtime) as client:
        response = await client.post(
            '/anthropic/v1/messages',
            headers={'x-api-key': 'github-token-123'},
            json=request_body,
        )

    payload = cast('dict[str, Any]', response.json())
    content = cast('list[dict[str, Any]]', payload['content'])
    assert response.status_code == 200
    assert payload['type'] == 'message'
    assert payload['role'] == 'assistant'
    assert payload['model'] == 'claude-sonnet-4-20250514'
    assert payload['stop_reason'] == 'end_turn'
    assert content == [{'type': 'text', 'text': 'HELLO'}]
    assert payload['usage'] == {'input_tokens': 11, 'output_tokens': 2}
    assert runtime.last_request is not None
    assert runtime.last_request.runtime_auth_token == 'github-token-123'  # noqa: S105 - deterministic test token
    assert [message.model_dump() for message in runtime.last_request.messages] == [
        {'role': 'system', 'content': 'You are terse.'},
        {'role': 'user', 'content': 'Reply with HELLO.'},
    ]


@pytest.mark.asyncio
async def test_post_messages_prefers_bearer_auth_over_api_key() -> None:
    """Verify that bearer auth wins when both Anthropic auth headers are present."""
    runtime = _FakeAnthropicRuntime()
    async with build_async_client(runtime=runtime) as client:
        response = await client.post(
            '/anthropic/v1/messages',
            headers={
                'Authorization': 'Bearer bearer-token-456',
                'x-api-key': 'api-key-should-not-win',
            },
            json={
                'model': 'claude-sonnet-4-20250514',
                'messages': [{'role': 'user', 'content': 'Hello'}],
            },
        )

    assert response.status_code == 200
    assert runtime.last_request is not None
    assert runtime.last_request.runtime_auth_token == 'bearer-token-456'  # noqa: S105 - deterministic test token


@pytest.mark.asyncio
async def test_post_messages_fall_back_to_configured_runtime_token() -> None:
    """Verify that configured runtime auth still works without request headers."""
    runtime = _FakeAnthropicRuntime()
    async with build_async_client(
        runtime=runtime,
        settings=ProviderSettings(
            environment='test',
            runtime_auth_token='github-token-789',  # noqa: S106 - deterministic test token
        ),
    ) as client:
        response = await client.post(
            '/anthropic/v1/messages',
            json={
                'model': 'claude-sonnet-4-20250514',
                'messages': [{'role': 'user', 'content': 'Hello'}],
            },
        )

    assert response.status_code == 200
    assert runtime.last_request is not None
    assert runtime.last_request.runtime_auth_token == 'github-token-789'  # noqa: S105 - deterministic test token


@pytest.mark.asyncio
async def test_post_messages_streams_anthropic_compatible_sse_frames() -> None:
    """Verify that streaming Messages requests emit Anthropic lifecycle frames."""
    runtime = _FakeAnthropicRuntime()
    async with (
        build_async_client(runtime=runtime) as client,
        client.stream(
            'POST',
            '/anthropic/v1/messages',
            headers={'x-api-key': 'github-token-123'},
            json={
                'model': 'claude-sonnet-4-20250514',
                'stream': True,
                'messages': [{'role': 'user', 'content': 'Hello'}],
            },
        ) as response,
    ):
        payload = ''.join([chunk async for chunk in response.aiter_text()])

    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/event-stream')
    assert 'event: message_start' in payload
    assert 'event: content_block_start' in payload
    assert 'event: content_block_delta' in payload
    assert '"text":"HEL"' in payload
    assert '"text":"LO"' in payload
    assert 'event: content_block_stop' in payload
    assert 'event: message_delta' in payload
    assert 'event: message_stop' in payload


@pytest.mark.asyncio
async def test_post_count_tokens_returns_anthropic_compatible_payload() -> None:
    """Verify that the count-tokens route returns an Anthropic-style token count."""
    runtime = _FakeAnthropicRuntime()
    request_body: dict[str, object] = {
        'model': 'claude-sonnet-4-20250514',
        'system': 'You are terse.',
        'metadata': {'source': 'claude-code'},
        'messages': [{'role': 'user', 'content': 'Reply with HELLO.'}],
        'tools': [{'name': 'read_file', 'input_schema': {'type': 'object'}}],
    }
    expected_input_tokens = estimate_anthropic_input_tokens(
        request=AnthropicMessagesCountTokensRequest.model_validate(request_body)
    )
    async with build_async_client(runtime=runtime) as client:
        response = await client.post(
            '/anthropic/v1/messages/count_tokens',
            headers={'x-api-key': 'github-token-123'},
            json=request_body,
        )

    assert response.status_code == 200
    assert response.json() == {'input_tokens': expected_input_tokens}
    assert runtime.last_request is None
