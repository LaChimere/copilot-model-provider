"""Contract tests for the OpenAI-compatible non-streaming chat endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING, override

import pytest
from copilot.generated.session_events import SessionEvent

from copilot_model_provider.config import ProviderSettings
from copilot_model_provider.core.models import (
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


class _FakeChatRuntime(RuntimeProtocol):
    """Deterministic runtime used by HTTP contract tests."""

    supported_model_ids = ('gpt-5.4', 'gpt-5.4-mini')

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
            output_text='Hello from the fake runtime.',
            provider_response_id='chatcmpl-contract',
            prompt_tokens=9,
            completion_tokens=6,
        )

    @override
    async def stream_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeEventStream:
        """Return a deterministic OpenAI-compatible stream for HTTP tests."""
        del request, route

        async def _events() -> AsyncIterator[SessionEvent]:
            """Yield a minimal assistant streaming turn for contract validation."""
            for event in (
                SessionEvent.from_dict(
                    {
                        'id': '00000000-0000-0000-0000-000000000001',
                        'timestamp': '2025-01-01T00:00:00Z',
                        'type': 'assistant.message_delta',
                        'data': {'deltaContent': 'Hello'},
                    }
                ),
                SessionEvent.from_dict(
                    {
                        'id': '00000000-0000-0000-0000-000000000002',
                        'timestamp': '2025-01-01T00:00:00Z',
                        'type': 'assistant.turn_end',
                        'data': {'reason': 'stop'},
                    }
                ),
            ):
                yield event

        return RuntimeEventStream(
            session_id=None,
            events=_events(),
        )

    @override
    async def discard_interactive_session(
        self,
        *,
        session_id: str,
        disconnect: bool,
    ) -> None:
        """Reject unexpected runtime cleanup calls in non-streaming chat tests."""
        del session_id, disconnect
        raise AssertionError(
            'discard_interactive_session should not be called in this test'
        )


class _FakeChatAggregateRuntime(_FakeChatRuntime):
    """Fake streaming runtime that emits a final aggregate assistant message."""

    @override
    async def stream_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeEventStream:
        """Emit both deltas and a final assistant.message to test de-duplication."""
        del request, route

        async def _events() -> AsyncIterator[SessionEvent]:
            """Yield a delta, an aggregate message, and a terminal turn-end event."""
            for event in (
                SessionEvent.from_dict(
                    {
                        'id': '00000000-0000-0000-0000-000000000011',
                        'timestamp': '2025-01-01T00:00:00Z',
                        'type': 'assistant.message_delta',
                        'data': {'deltaContent': 'Hello'},
                    }
                ),
                SessionEvent.from_dict(
                    {
                        'id': '00000000-0000-0000-0000-000000000012',
                        'timestamp': '2025-01-01T00:00:00Z',
                        'type': 'assistant.message',
                        'data': {'content': 'Hello'},
                    }
                ),
                SessionEvent.from_dict(
                    {
                        'id': '00000000-0000-0000-0000-000000000013',
                        'timestamp': '2025-01-01T00:00:00Z',
                        'type': 'assistant.turn_end',
                        'data': {'reason': 'stop'},
                    }
                ),
            ):
                yield event

        return RuntimeEventStream(
            session_id=None,
            events=_events(),
        )


@pytest.mark.asyncio
async def test_post_chat_completions_returns_openai_compatible_payload() -> None:
    """Verify that the HTTP route returns the expected non-streaming payload."""
    runtime = _FakeChatRuntime()
    async with build_async_client(runtime=runtime) as client:
        response = await client.post(
            '/openai/v1/chat/completions',
            json={
                'model': 'gpt-5.4',
                'messages': [{'role': 'user', 'content': 'Hello'}],
            },
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload['id'] == 'chatcmpl-contract'
    assert payload['object'] == 'chat.completion'
    assert isinstance(payload['created'], int)
    assert payload['model'] == 'gpt-5.4'
    assert payload['choices'] == [
        {
            'index': 0,
            'message': {
                'role': 'assistant',
                'content': 'Hello from the fake runtime.',
            },
            'finish_reason': 'stop',
        }
    ]
    assert payload['usage'] == {
        'prompt_tokens': 9,
        'completion_tokens': 6,
        'total_tokens': 15,
    }
    assert runtime.last_request is not None
    assert runtime.last_request.runtime_auth_token is None


@pytest.mark.asyncio
async def test_post_chat_completions_extracts_bearer_token() -> None:
    """Verify that bearer auth is normalized onto the canonical runtime request."""
    runtime = _FakeChatRuntime()
    async with build_async_client(runtime=runtime) as client:
        response = await client.post(
            '/openai/v1/chat/completions',
            headers={'Authorization': 'Bearer github-token-123'},
            json={
                'model': 'gpt-5.4',
                'messages': [{'role': 'user', 'content': 'Hello'}],
            },
        )

    assert response.status_code == 200
    assert runtime.last_request is not None
    assert runtime.last_request.runtime_auth_token == 'github-token-123'  # noqa: S105 - deterministic test token


@pytest.mark.asyncio
async def test_post_chat_completions_fall_back_to_configured_runtime_token() -> None:
    """Verify that requests without auth headers use the configured runtime token."""
    runtime = _FakeChatRuntime()
    async with build_async_client(
        runtime=runtime,
        settings=ProviderSettings(
            environment='test',
            runtime_auth_token='github-token-456',  # noqa: S106 - deterministic test token
        ),
    ) as client:
        response = await client.post(
            '/openai/v1/chat/completions',
            json={
                'model': 'gpt-5.4',
                'messages': [{'role': 'user', 'content': 'Hello'}],
            },
        )

    assert response.status_code == 200
    assert runtime.last_request is not None
    assert runtime.last_request.runtime_auth_token == 'github-token-456'  # noqa: S105 - deterministic test token


@pytest.mark.asyncio
async def test_post_chat_completions_prefer_request_auth_over_configured_runtime_token() -> (
    None
):
    """Verify that explicit request auth overrides the configured container token."""
    runtime = _FakeChatRuntime()
    async with build_async_client(
        runtime=runtime,
        settings=ProviderSettings(
            environment='test',
            runtime_auth_token='github-token-456',  # noqa: S106 - deterministic test token
        ),
    ) as client:
        response = await client.post(
            '/openai/v1/chat/completions',
            headers={'Authorization': 'Bearer github-token-123'},
            json={
                'model': 'gpt-5.4',
                'messages': [{'role': 'user', 'content': 'Hello'}],
            },
        )

    assert response.status_code == 200
    assert runtime.last_request is not None
    assert runtime.last_request.runtime_auth_token == 'github-token-123'  # noqa: S105 - deterministic test token


@pytest.mark.asyncio
async def test_post_chat_completions_rejects_non_bearer_authorization_headers() -> None:
    """Verify that malformed Authorization headers fail fast."""
    async with build_async_client(runtime=_FakeChatRuntime()) as client:
        response = await client.post(
            '/openai/v1/chat/completions',
            headers={'Authorization': 'Token github-token-123'},
            json={
                'model': 'gpt-5.4',
                'messages': [{'role': 'user', 'content': 'Hello'}],
            },
        )

    assert response.status_code == 400
    assert response.json()['error']['code'] == 'invalid_authorization_header'
