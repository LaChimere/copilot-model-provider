"""Contract tests for the Anthropic-compatible Messages endpoint."""

from __future__ import annotations

import asyncio
import importlib
import json
from typing import TYPE_CHECKING, Any, cast, override

import pytest
from copilot.generated.session_events import SessionEvent

import copilot_model_provider.api.anthropic.messages as anthropic_messages_api
from copilot_model_provider.api.anthropic.protocol import (
    estimate_anthropic_input_tokens,
    estimate_anthropic_output_tokens,
)
from copilot_model_provider.config import ProviderSettings
from copilot_model_provider.core.compat import FieldHandling, ProtocolSurface
from copilot_model_provider.core.models import (
    AnthropicMessagesCountTokensRequest,
    CanonicalChatRequest,
    CanonicalToolCall,
    ResolvedRoute,
    RuntimeCompletion,
    RuntimeHealth,
)
from copilot_model_provider.runtimes.protocols import (
    RuntimeEventStream,
    RuntimeProtocol,
)
from tests.contract_tests.helpers import assert_payload_field_handling, parse_sse_frames
from tests.harness import build_async_client

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_ANTHROPIC_TOOL_SESSION_ID = 'anthropic-tool-session'
_ANTHROPIC_TOOL_CALL_ID = 'toolu_123'
_ANTHROPIC_READ_FILE_ARGUMENTS = {'path': 'README.md'}


def _build_read_file_tool_definition() -> dict[str, object]:
    """Return the Anthropic tool descriptor used for tool-loop coverage."""
    return {
        'name': 'read_file',
        'description': 'Read one file.',
        'input_schema': {'type': 'object'},
    }


def _extract_tool_use_blocks(*, content: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return all ``tool_use`` blocks from one Anthropic message payload."""
    return [block for block in content if block.get('type') == 'tool_use']


class _CapturedLogger:
    """Record Anthropic route header logs for contract verification."""

    def __init__(self) -> None:
        """Initialize the in-memory event sink."""
        self.events: list[tuple[str, dict[str, object]]] = []

    def info(self, event: str, **kwargs: object) -> None:
        """Record one informational log event."""
        self.events.append((event, kwargs))


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
                        'type': 'assistant.usage',
                        'data': {'inputTokens': 11, 'outputTokens': 2},
                    }
                ),
                SessionEvent.from_dict(
                    {
                        'id': '10000000-0000-0000-0000-000000000003',
                        'timestamp': '2025-01-01T00:00:00Z',
                        'type': 'assistant.message_delta',
                        'data': {'deltaContent': 'LO'},
                    }
                ),
                SessionEvent.from_dict(
                    {
                        'id': '10000000-0000-0000-0000-000000000004',
                        'timestamp': '2025-01-01T00:00:00Z',
                        'type': 'assistant.turn_end',
                        'data': {'reason': 'stop'},
                    }
                ),
            ):
                yield event

        return RuntimeEventStream(session_id=None, events=_events())

    @override
    async def discard_interactive_session(
        self,
        *,
        session_id: str,
        disconnect: bool,
    ) -> None:
        """Reject unexpected runtime cleanup calls in Anthropic contract tests."""
        del session_id, disconnect
        raise AssertionError(
            'discard_interactive_session should not be called in this test'
        )


class _ZeroUsageAnthropicRuntime(_FakeAnthropicRuntime):
    """Fake Anthropic runtime that reports exact zero completion tokens."""

    @override
    async def stream_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeEventStream:
        """Emit usage metadata with an exact zero output-token count."""
        del route
        self.last_request = request

        async def _events() -> AsyncIterator[SessionEvent]:
            """Yield usage metadata before a zero-output terminal turn."""
            for event in (
                SessionEvent.from_dict(
                    {
                        'id': '10000000-0000-0000-0000-000000000101',
                        'timestamp': '2025-01-01T00:00:00Z',
                        'type': 'assistant.usage',
                        'data': {'inputTokens': 11, 'outputTokens': 0},
                    }
                ),
                SessionEvent.from_dict(
                    {
                        'id': '10000000-0000-0000-0000-000000000102',
                        'timestamp': '2025-01-01T00:00:00Z',
                        'type': 'assistant.turn_end',
                        'data': {'reason': 'stop'},
                    }
                ),
            ):
                yield event

        return RuntimeEventStream(session_id=None, events=_events())


class _FakeAnthropicToolRuntime(_FakeAnthropicRuntime):
    """Fake runtime that pauses on tool use and resumes on tool results."""

    def __init__(self) -> None:
        """Initialize the fake runtime state for Anthropic tool-loop tests."""
        super().__init__()
        self.discarded_sessions: list[tuple[str, bool]] = []

    @override
    async def complete_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeCompletion:
        """Return tool_use first, then final text after the tool result arrives."""
        del route
        self.last_request = request
        if request.tool_results:
            return RuntimeCompletion(
                output_text='Final answer.',
                session_id=request.session_id,
                prompt_tokens=12,
                completion_tokens=2,
            )

        return RuntimeCompletion(
            output_text='Thinking...',
            finish_reason='tool_calls',
            session_id=_ANTHROPIC_TOOL_SESSION_ID,
            pending_tool_calls=(
                CanonicalToolCall(
                    call_id=_ANTHROPIC_TOOL_CALL_ID,
                    name='read_file',
                    arguments=_ANTHROPIC_READ_FILE_ARGUMENTS,
                ),
            ),
            prompt_tokens=8,
            completion_tokens=2,
        )

    @override
    async def stream_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeEventStream:
        """Emit a tool_use block during streaming."""
        del route
        self.last_request = request

        async def _events() -> AsyncIterator[SessionEvent]:
            """Yield a tool-use turn."""
            for event in (
                SessionEvent.from_dict(
                    {
                        'id': '20000000-0000-0000-0000-000000000001',
                        'timestamp': '2025-01-01T00:00:00Z',
                        'type': 'assistant.message_delta',
                        'data': {'deltaContent': 'Think'},
                    }
                ),
                SessionEvent.from_dict(
                    {
                        'id': '20000000-0000-0000-0000-000000000002',
                        'timestamp': '2025-01-01T00:00:00Z',
                        'type': 'external_tool.requested',
                        'data': {
                            'requestId': 'anthropic-tool-request',
                            'toolName': 'read_file',
                            'toolCallId': _ANTHROPIC_TOOL_CALL_ID,
                            'arguments': _ANTHROPIC_READ_FILE_ARGUMENTS,
                        },
                    }
                ),
            ):
                yield event

        return RuntimeEventStream(
            session_id=_ANTHROPIC_TOOL_SESSION_ID, events=_events()
        )

    @override
    async def discard_interactive_session(
        self,
        *,
        session_id: str,
        disconnect: bool,
    ) -> None:
        """Record runtime cleanup calls expected by Anthropic expiry tests."""
        self.discarded_sessions.append((session_id, disconnect))


class _BlockingAnthropicToolRuntime(_FakeAnthropicToolRuntime):
    """Fake runtime that blocks a continuation so duplicate Anthropic follow-ups can race."""

    def __init__(self) -> None:
        """Initialize the blocking continuation controls used by concurrency tests."""
        super().__init__()
        self.release_continuation = asyncio.Event()
        self.continuation_call_count = 0

    @override
    async def complete_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeCompletion:
        """Block tool-result continuations so duplicate requests can overlap."""
        if request.tool_results:
            self.continuation_call_count += 1
            await self.release_continuation.wait()
        return await super().complete_chat(request=request, route=route)


class _FakeAnthropicMultiToolRuntime(_FakeAnthropicRuntime):
    """Fake runtime that pauses on two tool_use blocks before resuming."""

    @override
    async def complete_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeCompletion:
        """Return two tool_use blocks first, then final text after both results."""
        del route
        self.last_request = request
        if request.tool_results:
            return RuntimeCompletion(
                output_text='Final multi-tool answer.',
                session_id=request.session_id,
                prompt_tokens=16,
                completion_tokens=3,
            )

        return RuntimeCompletion(
            output_text='Thinking...',
            finish_reason='tool_calls',
            session_id='anthropic-multi-tool-session',
            pending_tool_calls=(
                CanonicalToolCall(
                    call_id='toolu_readme',
                    name='read_file',
                    arguments={'path': 'README.md'},
                ),
                CanonicalToolCall(
                    call_id='toolu_docs',
                    name='list_dir',
                    arguments={'path': 'docs'},
                ),
            ),
            prompt_tokens=10,
            completion_tokens=2,
        )

    @override
    async def stream_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeEventStream:
        """Emit two tool_use blocks during streaming."""
        del route
        self.last_request = request

        async def _events() -> AsyncIterator[SessionEvent]:
            """Yield a multi-tool Anthropic turn."""
            for event in (
                SessionEvent.from_dict(
                    {
                        'id': '20000000-0000-0000-0000-000000000101',
                        'timestamp': '2025-01-01T00:00:00Z',
                        'type': 'assistant.message_delta',
                        'data': {'deltaContent': 'Think'},
                    }
                ),
                SessionEvent.from_dict(
                    {
                        'id': '20000000-0000-0000-0000-000000000102',
                        'timestamp': '2025-01-01T00:00:00Z',
                        'type': 'external_tool.requested',
                        'data': {
                            'requestId': 'anthropic-tool-request-1',
                            'toolName': 'read_file',
                            'toolCallId': 'toolu_readme',
                            'arguments': {'path': 'README.md'},
                        },
                    }
                ),
                SessionEvent.from_dict(
                    {
                        'id': '20000000-0000-0000-0000-000000000103',
                        'timestamp': '2025-01-01T00:00:00Z',
                        'type': 'external_tool.requested',
                        'data': {
                            'requestId': 'anthropic-tool-request-2',
                            'toolName': 'list_dir',
                            'toolCallId': 'toolu_docs',
                            'arguments': {'path': 'docs'},
                        },
                    }
                ),
                SessionEvent.from_dict(
                    {
                        'id': '20000000-0000-0000-0000-000000000104',
                        'timestamp': '2025-01-01T00:00:00Z',
                        'type': 'assistant.turn_end',
                        'data': {'reason': 'tool_calls'},
                    }
                ),
            ):
                yield event

        return RuntimeEventStream(
            session_id='anthropic-multi-tool-session',
            events=_events(),
        )


class _FakeAnthropicReplayHistoryRuntime(_FakeAnthropicRuntime):
    """Fake runtime that replays one old tool_result before a later tool batch."""

    @override
    async def complete_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeCompletion:
        """Return one tool, then a second batch, then a final response."""
        del route
        self.last_request = request
        tool_result_call_ids = [result.call_id for result in request.tool_results]
        if not tool_result_call_ids:
            return RuntimeCompletion(
                output_text='Planning...',
                finish_reason='tool_calls',
                session_id='anthropic-replay-session',
                pending_tool_calls=(
                    CanonicalToolCall(
                        call_id='toolu_skill',
                        name='skill',
                        arguments={'skill': 'research'},
                    ),
                ),
            )
        if tool_result_call_ids == ['toolu_skill']:
            return RuntimeCompletion(
                output_text='Investigating...',
                finish_reason='tool_calls',
                session_id='anthropic-replay-session',
                pending_tool_calls=(
                    CanonicalToolCall(
                        call_id='toolu_readme',
                        name='read_file',
                        arguments={'path': 'README.md'},
                    ),
                    CanonicalToolCall(
                        call_id='toolu_docs',
                        name='list_dir',
                        arguments={'path': 'docs'},
                    ),
                ),
            )
        if tool_result_call_ids == ['toolu_readme', 'toolu_docs']:
            return RuntimeCompletion(
                output_text='Replay-safe final answer.',
                session_id=request.session_id,
            )

        msg = f'Unexpected tool results: {tool_result_call_ids!r}'
        raise AssertionError(msg)


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
async def test_post_messages_accepts_thinking_for_compatibility_without_passthrough() -> (
    None
):
    """Verify that ``thinking`` is accepted even though the runtime path ignores it."""
    runtime = _FakeAnthropicRuntime()
    request_body: dict[str, object] = {
        'model': 'claude-sonnet-4-20250514',
        'messages': [{'role': 'user', 'content': 'Hello'}],
        'thinking': {'type': 'enabled', 'budget_tokens': 256},
    }

    assert_payload_field_handling(
        surface=ProtocolSurface.ANTHROPIC_MESSAGES,
        payload=request_body,
        allowed=(FieldHandling.SUPPORTED, FieldHandling.ACCEPT_IGNORE),
    )

    async with build_async_client(runtime=runtime) as client:
        response = await client.post('/anthropic/v1/messages', json=request_body)

    assert response.status_code == 200
    assert runtime.last_request is not None
    assert [message.model_dump() for message in runtime.last_request.messages] == [
        {'role': 'user', 'content': 'Hello'}
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
async def test_post_messages_logs_gateway_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that Anthropic gateway headers are surfaced through structured logs."""
    messages_module = importlib.import_module(
        'copilot_model_provider.api.anthropic.messages'
    )
    captured_logger = _CapturedLogger()
    monkeypatch.setattr(messages_module, '_logger', captured_logger)

    async with build_async_client(runtime=_FakeAnthropicRuntime()) as client:
        response = await client.post(
            '/anthropic/v1/messages',
            headers={
                'x-api-key': 'github-token-123',
                'anthropic-version': '2023-06-01',
                'anthropic-beta': 'tools-2025-01-01',
                'X-Claude-Code-Session-Id': 'session-123',
            },
            json={
                'model': 'claude-sonnet-4-20250514',
                'messages': [{'role': 'user', 'content': 'Hello'}],
            },
        )

    assert response.status_code == 200
    assert (
        'anthropic_gateway_headers',
        {
            'surface': 'messages',
            'anthropic_version': '2023-06-01',
            'anthropic_beta': 'tools-2025-01-01',
            'claude_code_session_id': 'session-123',
        },
    ) in captured_logger.events


@pytest.mark.asyncio
async def test_post_messages_rejects_invalid_authorization_headers_with_anthropic_error_shape() -> (
    None
):
    """Verify that malformed auth uses the Anthropic non-streaming error envelope."""
    async with build_async_client(runtime=_FakeAnthropicRuntime()) as client:
        response = await client.post(
            '/anthropic/v1/messages',
            headers={'Authorization': 'Token github-token-123'},
            json={
                'model': 'claude-sonnet-4-20250514',
                'messages': [{'role': 'user', 'content': 'Hello'}],
            },
        )

    assert response.status_code == 400
    assert response.json() == {
        'type': 'error',
        'error': {
            'type': 'authentication_error',
            'message': 'Authorization header must use the Bearer token format.',
        },
    }


@pytest.mark.asyncio
async def test_post_messages_streams_anthropic_compatible_sse_frames() -> None:
    """Verify that streaming Messages requests emit Anthropic lifecycle frames."""
    runtime = _FakeAnthropicRuntime()
    request_body: dict[str, object] = {
        'model': 'claude-sonnet-4-20250514',
        'stream': True,
        'messages': [{'role': 'user', 'content': 'Hello'}],
    }
    expected_input_tokens = estimate_anthropic_input_tokens(
        request=AnthropicMessagesCountTokensRequest.model_validate(request_body)
    )
    async with (
        build_async_client(runtime=runtime) as client,
        client.stream(
            'POST',
            '/anthropic/v1/messages',
            headers={'x-api-key': 'github-token-123'},
            json=request_body,
        ) as response,
    ):
        payload = ''.join([chunk async for chunk in response.aiter_text()])

    frames = parse_sse_frames(payload=payload)
    message_start_frame = next(
        frame for frame in frames if frame.get('event') == 'message_start'
    )
    message_delta_frame = next(
        frame for frame in frames if frame.get('event') == 'message_delta'
    )
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
    assert (
        f'"usage":{{"input_tokens":{expected_input_tokens},"output_tokens":0}}'
        in message_start_frame['data']
    )
    assert (
        '"usage":{"input_tokens":11,"output_tokens":2}' in message_delta_frame['data']
    )


@pytest.mark.asyncio
async def test_post_messages_supports_tool_result_continuation() -> None:
    """Verify that non-streaming Anthropic tool_use turns can continue later."""
    runtime = _FakeAnthropicToolRuntime()
    first_request_body: dict[str, object] = {
        'model': 'claude-sonnet-4-20250514',
        'messages': [{'role': 'user', 'content': 'Read the README'}],
        'tools': [_build_read_file_tool_definition()],
    }
    async with build_async_client(runtime=runtime) as client:
        first_response = await client.post(
            '/anthropic/v1/messages',
            json=first_request_body,
        )

        first_payload = cast('dict[str, Any]', first_response.json())
        tool_use_block = cast('dict[str, Any]', first_payload['content'][1])
        follow_up_request_body: dict[str, object] = {
            'model': 'claude-sonnet-4-20250514',
            'messages': [
                {
                    'role': 'user',
                    'content': [
                        {
                            'type': 'tool_result',
                            'tool_use_id': tool_use_block['id'],
                            'content': 'README contents',
                        }
                    ],
                }
            ],
        }
        follow_up = await client.post(
            '/anthropic/v1/messages',
            json=follow_up_request_body,
        )

    follow_up_payload = cast('dict[str, Any]', follow_up.json())
    assert first_response.status_code == 200
    assert first_payload['stop_reason'] == 'tool_use'
    assert tool_use_block['type'] == 'tool_use'
    assert follow_up.status_code == 200
    assert follow_up_payload['content'] == [{'type': 'text', 'text': 'Final answer.'}]
    assert runtime.last_request is not None
    assert runtime.last_request.session_id == _ANTHROPIC_TOOL_SESSION_ID
    assert [result.model_dump() for result in runtime.last_request.tool_results] == [
        {
            'call_id': _ANTHROPIC_TOOL_CALL_ID,
            'output_text': 'README contents',
            'is_error': False,
            'error_text': None,
        }
    ]


@pytest.mark.asyncio
async def test_post_messages_rejects_sequential_duplicate_tool_result_continuation() -> (
    None
):
    """Verify one Anthropic paused turn cannot be resumed twice with the same tool result."""
    runtime = _FakeAnthropicToolRuntime()
    first_request_body: dict[str, object] = {
        'model': 'claude-sonnet-4-20250514',
        'messages': [{'role': 'user', 'content': 'Read the README'}],
        'tools': [_build_read_file_tool_definition()],
    }
    async with build_async_client(runtime=runtime) as client:
        first_response = await client.post(
            '/anthropic/v1/messages',
            json=first_request_body,
        )

        first_payload = cast('dict[str, Any]', first_response.json())
        tool_use_block = cast('dict[str, Any]', first_payload['content'][1])
        first_follow_up = await client.post(
            '/anthropic/v1/messages',
            json={
                'model': 'claude-sonnet-4-20250514',
                'messages': [
                    {
                        'role': 'user',
                        'content': [
                            {
                                'type': 'tool_result',
                                'tool_use_id': tool_use_block['id'],
                                'content': 'README contents',
                            }
                        ],
                    }
                ],
            },
        )
        second_follow_up = await client.post(
            '/anthropic/v1/messages',
            json={
                'model': 'claude-sonnet-4-20250514',
                'messages': [
                    {
                        'role': 'user',
                        'content': [
                            {
                                'type': 'tool_result',
                                'tool_use_id': tool_use_block['id'],
                                'content': 'README contents',
                            }
                        ],
                    }
                ],
            },
        )

    assert first_response.status_code == 200
    assert first_follow_up.status_code == 200
    assert second_follow_up.status_code == 400
    second_error = cast('dict[str, Any]', second_follow_up.json())['error']
    assert second_error['message'] == (
        'No pending provider session matched the supplied tool_result blocks.'
    )


@pytest.mark.asyncio
async def test_post_messages_concurrent_duplicate_tool_result_continuations_resume_only_once() -> (
    None
):
    """Verify concurrent Anthropic duplicate follow-ups cannot resume one turn twice."""
    runtime = _BlockingAnthropicToolRuntime()
    first_request_body: dict[str, object] = {
        'model': 'claude-sonnet-4-20250514',
        'messages': [{'role': 'user', 'content': 'Read the README'}],
        'tools': [_build_read_file_tool_definition()],
    }
    async with build_async_client(runtime=runtime) as client:
        first_response = await client.post(
            '/anthropic/v1/messages',
            json=first_request_body,
        )
        first_payload = cast('dict[str, Any]', first_response.json())
        tool_use_block = cast('dict[str, Any]', first_payload['content'][1])

        async def _submit_follow_up() -> tuple[int, dict[str, Any]]:
            """Submit one duplicated Anthropic continuation against the same tool use."""
            response = await client.post(
                '/anthropic/v1/messages',
                json={
                    'model': 'claude-sonnet-4-20250514',
                    'messages': [
                        {
                            'role': 'user',
                            'content': [
                                {
                                    'type': 'tool_result',
                                    'tool_use_id': tool_use_block['id'],
                                    'content': 'README contents',
                                }
                            ],
                        }
                    ],
                },
            )
            return response.status_code, cast('dict[str, Any]', response.json())

        first_follow_up_task = asyncio.create_task(_submit_follow_up())
        await asyncio.sleep(0)
        second_follow_up_task = asyncio.create_task(_submit_follow_up())
        await asyncio.sleep(0)
        runtime.release_continuation.set()
        follow_up_results = await asyncio.gather(
            first_follow_up_task,
            second_follow_up_task,
        )

    statuses = sorted(status for status, _ in follow_up_results)
    error_payload = next(
        payload for status, payload in follow_up_results if status == 400
    )

    assert first_response.status_code == 200
    assert statuses == [200, 400]
    assert error_payload['error']['message'] == (
        'No pending provider session matched the supplied tool_result blocks.'
    )
    assert runtime.continuation_call_count == 1


@pytest.mark.asyncio
async def test_post_messages_continuation_expires_after_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that abandoned Anthropic continuations expire instead of leaking forever."""
    monkeypatch.setattr(
        anthropic_messages_api,
        '_PENDING_TOOL_USE_SESSION_TTL_SECONDS',
        0.01,
    )
    runtime = _FakeAnthropicToolRuntime()
    first_request_body: dict[str, object] = {
        'model': 'claude-sonnet-4-20250514',
        'messages': [{'role': 'user', 'content': 'Read the README'}],
        'tools': [_build_read_file_tool_definition()],
    }
    async with build_async_client(runtime=runtime) as client:
        first_response = await client.post(
            '/anthropic/v1/messages',
            json=first_request_body,
        )

        first_payload = cast('dict[str, Any]', first_response.json())
        tool_use_block = cast('dict[str, Any]', first_payload['content'][1])
        await asyncio.sleep(0.05)
        follow_up_request_body: dict[str, object] = {
            'model': 'claude-sonnet-4-20250514',
            'messages': [
                {
                    'role': 'user',
                    'content': [
                        {
                            'type': 'tool_result',
                            'tool_use_id': tool_use_block['id'],
                            'content': 'README contents',
                        }
                    ],
                }
            ],
        }
        follow_up = await client.post(
            '/anthropic/v1/messages',
            json=follow_up_request_body,
        )

    follow_up_payload = cast('dict[str, Any]', follow_up.json())
    assert first_response.status_code == 200
    assert follow_up.status_code == 400
    assert follow_up_payload['error']['message'] == (
        'No pending provider session matched the supplied tool_result blocks.'
    )
    assert runtime.discarded_sessions == [(_ANTHROPIC_TOOL_SESSION_ID, True)]


@pytest.mark.asyncio
async def test_post_messages_require_full_tool_result_batch() -> None:
    """Verify that Anthropic continuations must submit the full pending tool batch."""
    runtime = _FakeAnthropicMultiToolRuntime()
    first_request_body: dict[str, object] = {
        'model': 'claude-sonnet-4-20250514',
        'messages': [{'role': 'user', 'content': 'Inspect the repo'}],
        'tools': [
            _build_read_file_tool_definition(),
            {
                'name': 'list_dir',
                'description': 'List one directory.',
                'input_schema': {'type': 'object'},
            },
        ],
    }
    async with build_async_client(runtime=runtime) as client:
        partial_follow_up_request: dict[str, object] = {
            'model': 'claude-sonnet-4-20250514',
            'messages': [
                {
                    'role': 'user',
                    'content': [
                        {
                            'type': 'tool_result',
                            'tool_use_id': 'toolu_readme',
                            'content': 'README contents',
                        }
                    ],
                }
            ],
        }
        full_follow_up_request: dict[str, object] = {
            'model': 'claude-sonnet-4-20250514',
            'messages': [
                {
                    'role': 'user',
                    'content': [
                        {
                            'type': 'tool_result',
                            'tool_use_id': 'toolu_readme',
                            'content': 'README contents',
                        },
                        {
                            'type': 'tool_result',
                            'tool_use_id': 'toolu_docs',
                            'content': 'docs/',
                        },
                    ],
                }
            ],
        }
        first_response = await client.post(
            '/anthropic/v1/messages',
            json=first_request_body,
        )

        first_payload = cast('dict[str, Any]', first_response.json())
        tool_use_blocks = _extract_tool_use_blocks(
            content=cast('list[dict[str, Any]]', first_payload['content'])
        )
        partial_follow_up = await client.post(
            '/anthropic/v1/messages',
            json=partial_follow_up_request,
        )
        full_follow_up = await client.post(
            '/anthropic/v1/messages',
            json=full_follow_up_request,
        )

    assert first_response.status_code == 200
    assert [block['id'] for block in tool_use_blocks] == ['toolu_readme', 'toolu_docs']
    assert partial_follow_up.status_code == 400
    partial_error_payload = cast('dict[str, Any]', partial_follow_up.json())
    assert partial_error_payload['type'] == 'error'
    assert partial_error_payload['error']['message'] == (
        'Tool result blocks must provide the full pending tool-result batch.'
    )
    assert full_follow_up.status_code == 200
    assert runtime.last_request is not None
    assert runtime.last_request.session_id == 'anthropic-multi-tool-session'
    assert [result.call_id for result in runtime.last_request.tool_results] == [
        'toolu_readme',
        'toolu_docs',
    ]


@pytest.mark.asyncio
async def test_post_messages_ignores_historical_tool_results_during_replay_continuation() -> (
    None
):
    """Verify that Anthropic replay continuations keep only the current tool batch."""
    runtime = _FakeAnthropicReplayHistoryRuntime()
    async with build_async_client(runtime=runtime) as client:
        first_request_body: dict[str, object] = {
            'model': 'claude-sonnet-4-20250514',
            'messages': [{'role': 'user', 'content': 'Research the repo'}],
            'tools': [
                {
                    'name': 'skill',
                    'description': 'Run one skill.',
                    'input_schema': {'type': 'object'},
                },
                _build_read_file_tool_definition(),
                {
                    'name': 'list_dir',
                    'description': 'List one directory.',
                    'input_schema': {'type': 'object'},
                },
            ],
        }
        first_response = await client.post(
            '/anthropic/v1/messages',
            json=first_request_body,
        )
        first_payload = cast('dict[str, Any]', first_response.json())
        first_tool_use = _extract_tool_use_blocks(
            content=cast('list[dict[str, Any]]', first_payload['content'])
        )[0]

        second_request_body: dict[str, object] = {
            'model': 'claude-sonnet-4-20250514',
            'messages': [
                {
                    'role': 'user',
                    'content': [
                        {
                            'type': 'tool_result',
                            'tool_use_id': first_tool_use['id'],
                            'content': 'skill finished',
                        }
                    ],
                }
            ],
        }
        second_response = await client.post(
            '/anthropic/v1/messages',
            json=second_request_body,
        )
        second_payload = cast('dict[str, Any]', second_response.json())
        second_tool_uses = _extract_tool_use_blocks(
            content=cast('list[dict[str, Any]]', second_payload['content'])
        )

        third_request_body: dict[str, object] = {
            'model': 'claude-sonnet-4-20250514',
            'messages': [
                {
                    'role': 'user',
                    'content': [
                        {
                            'type': 'tool_result',
                            'tool_use_id': first_tool_use['id'],
                            'content': 'skill finished',
                        },
                        {
                            'type': 'tool_result',
                            'tool_use_id': 'toolu_readme',
                            'content': 'README contents',
                        },
                        {
                            'type': 'tool_result',
                            'tool_use_id': 'toolu_docs',
                            'content': 'docs/',
                        },
                    ],
                }
            ],
        }
        third_response = await client.post(
            '/anthropic/v1/messages',
            json=third_request_body,
        )

    third_payload = cast('dict[str, Any]', third_response.json())
    assert first_response.status_code == 200
    assert first_tool_use['id'] == 'toolu_skill'
    assert second_response.status_code == 200
    assert [block['id'] for block in second_tool_uses] == ['toolu_readme', 'toolu_docs']
    assert third_response.status_code == 200
    assert third_payload['content'] == [
        {'type': 'text', 'text': 'Replay-safe final answer.'}
    ]
    assert runtime.last_request is not None
    assert [result.call_id for result in runtime.last_request.tool_results] == [
        'toolu_readme',
        'toolu_docs',
    ]


@pytest.mark.asyncio
async def test_post_messages_streaming_emits_tool_use_blocks() -> None:
    """Verify that Anthropic streaming can surface a tool_use turn."""
    runtime = _FakeAnthropicToolRuntime()
    request_body: dict[str, object] = {
        'model': 'claude-sonnet-4-20250514',
        'stream': True,
        'messages': [{'role': 'user', 'content': 'Read the README'}],
        'tools': [_build_read_file_tool_definition()],
    }
    async with (
        build_async_client(runtime=runtime) as client,
        client.stream(
            'POST',
            '/anthropic/v1/messages',
            json=request_body,
        ) as response,
    ):
        payload = ''.join([chunk async for chunk in response.aiter_text()])

    assert response.status_code == 200
    assert 'event: content_block_start' in payload
    assert '"type":"tool_use"' in payload
    assert f'"id":"{_ANTHROPIC_TOOL_CALL_ID}"' in payload
    assert '"stop_reason":"tool_use"' in payload


@pytest.mark.asyncio
async def test_post_messages_streaming_emits_multiple_tool_use_blocks() -> None:
    """Verify that Anthropic streaming can surface multiple tool_use blocks."""
    runtime = _FakeAnthropicMultiToolRuntime()
    request_body: dict[str, object] = {
        'model': 'claude-sonnet-4-20250514',
        'stream': True,
        'messages': [{'role': 'user', 'content': 'Inspect the repo'}],
        'tools': [
            _build_read_file_tool_definition(),
            {
                'name': 'list_dir',
                'description': 'List one directory.',
                'input_schema': {'type': 'object'},
            },
        ],
    }
    async with (
        build_async_client(runtime=runtime) as client,
        client.stream(
            'POST',
            '/anthropic/v1/messages',
            json=request_body,
        ) as response,
    ):
        payload = ''.join([chunk async for chunk in response.aiter_text()])

    assert response.status_code == 200
    assert payload.count('"type":"tool_use"') == 2
    assert '"id":"toolu_readme"' in payload
    assert '"id":"toolu_docs"' in payload
    assert '"stop_reason":"tool_use"' in payload

    frames = parse_sse_frames(payload=payload)
    content_block_frames = [
        frame
        for frame in frames
        if frame.get('event') in {'content_block_start', 'content_block_stop'}
    ]
    frame_indexes = [
        json.loads(frame['data'])['index'] for frame in content_block_frames
    ]

    assert frame_indexes == [0, 0, 1, 1, 2, 2]


def test_estimate_anthropic_output_tokens_uses_count_tokens_heuristic() -> None:
    """Verify that output-token estimation uses the same bytes-per-token heuristic."""
    assert estimate_anthropic_output_tokens(output_text='HELLO') == 2


@pytest.mark.asyncio
async def test_post_messages_streaming_preserves_exact_zero_usage_tokens() -> None:
    """Verify that exact zero usage is not replaced by an estimate."""
    async with (
        build_async_client(runtime=_ZeroUsageAnthropicRuntime()) as client,
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

    frames = parse_sse_frames(payload=payload)
    message_delta_frame = next(
        frame for frame in frames if frame.get('event') == 'message_delta'
    )

    assert response.status_code == 200
    assert (
        '"usage":{"input_tokens":11,"output_tokens":0}' in message_delta_frame['data']
    )


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
