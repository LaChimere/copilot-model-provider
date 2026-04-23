"""Contract tests for the OpenAI-compatible streaming chat endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING, override

import pytest
from copilot.generated.session_events import SessionEvent

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
from tests.contract_tests.helpers import parse_sse_frames
from tests.harness import build_async_client

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class _FakeStreamingChatRuntime(RuntimeProtocol):
    """Deterministic runtime used by streaming chat contract tests."""

    supported_model_ids = ('gpt-5.4', 'gpt-5.4-mini')

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
        """Reject non-streaming execution in the streaming-only test double."""
        del request, route
        msg = 'Streaming contract runtime should not receive non-streaming calls.'
        raise AssertionError(msg)

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
                        'id': '00000000-0000-0000-0000-000000000101',
                        'timestamp': '2025-01-01T00:00:00Z',
                        'type': 'assistant.message_delta',
                        'data': {'deltaContent': 'Hello'},
                    }
                ),
                SessionEvent.from_dict(
                    {
                        'id': '00000000-0000-0000-0000-000000000102',
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
        """Reject unexpected runtime cleanup calls in streaming chat tests."""
        del session_id, disconnect
        raise AssertionError(
            'discard_interactive_session should not be called in this test'
        )


class _FakeAggregateStreamingChatRuntime(_FakeStreamingChatRuntime):
    """Fake runtime that emits both deltas and a final aggregate assistant message."""

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
                        'id': '00000000-0000-0000-0000-000000000111',
                        'timestamp': '2025-01-01T00:00:00Z',
                        'type': 'assistant.message_delta',
                        'data': {'deltaContent': 'Hello'},
                    }
                ),
                SessionEvent.from_dict(
                    {
                        'id': '00000000-0000-0000-0000-000000000112',
                        'timestamp': '2025-01-01T00:00:00Z',
                        'type': 'assistant.message',
                        'data': {'content': 'Hello'},
                    }
                ),
                SessionEvent.from_dict(
                    {
                        'id': '00000000-0000-0000-0000-000000000113',
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
async def test_post_chat_completions_streams_openai_compatible_sse_frames() -> None:
    """Verify that streaming requests emit OpenAI-compatible SSE frames."""
    async with (
        build_async_client(runtime=_FakeStreamingChatRuntime()) as client,
        client.stream(
            'POST',
            '/openai/v1/chat/completions',
            json={
                'model': 'gpt-5.4',
                'stream': True,
                'messages': [{'role': 'user', 'content': 'Hello'}],
            },
        ) as response,
    ):
        payload = ''.join([chunk async for chunk in response.aiter_text()])

    frames = parse_sse_frames(payload=payload)
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/event-stream')
    assert frames[0]['data'].startswith('{"id":"chatcmpl-')
    assert '"object":"chat.completion.chunk"' in frames[0]['data']
    assert '"content":"Hello"' in frames[0]['data']
    assert frames[-1]['data'] == '[DONE]'


@pytest.mark.asyncio
async def test_post_chat_completions_streaming_deduplicates_final_aggregate_message() -> (
    None
):
    """Verify that aggregate assistant.message events do not duplicate streamed text."""
    async with (
        build_async_client(runtime=_FakeAggregateStreamingChatRuntime()) as client,
        client.stream(
            'POST',
            '/openai/v1/chat/completions',
            json={
                'model': 'gpt-5.4',
                'stream': True,
                'messages': [{'role': 'user', 'content': 'Hello'}],
            },
        ) as response,
    ):
        payload = ''.join([chunk async for chunk in response.aiter_text()])

    frames = parse_sse_frames(payload=payload)
    chunk_payloads = [
        frame['data'] for frame in frames if frame.get('data') != '[DONE]'
    ]

    assert response.status_code == 200
    assert len(chunk_payloads) == 2
    assert sum(payload.count('"content":"Hello"') for payload in chunk_payloads) == 1
