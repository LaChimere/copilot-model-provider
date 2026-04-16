"""Contract tests for the OpenAI-compatible Responses endpoint."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast, override

import pytest
from copilot.generated.session_events import SessionEvent

from copilot_model_provider.config import ProviderSettings
from copilot_model_provider.core.compat import FieldHandling, ProtocolSurface
from copilot_model_provider.core.models import (
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


class _FakeResponsesRuntime(RuntimeProtocol):
    """Deterministic runtime used by Responses HTTP contract tests."""

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
        """Return a deterministic Responses-compatible event stream for tests."""
        del route
        self.last_request = request

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
                        'data': {
                            'reason': 'stop',
                            'inputTokens': 9,
                            'outputTokens': 6,
                        },
                    }
                ),
            ):
                yield event

        return RuntimeEventStream(session_id=None, events=_events())


class _FakeResponsesAggregateRuntime(_FakeResponsesRuntime):
    """Fake streaming runtime that emits a final aggregate assistant message."""

    @override
    async def stream_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeEventStream:
        """Emit both deltas and a final assistant.message to test de-duplication."""
        del route
        self.last_request = request

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

        return RuntimeEventStream(session_id=None, events=_events())


class _FakeResponsesToolRuntime(_FakeResponsesRuntime):
    """Fake runtime that pauses on a function call and resumes on tool output."""

    @override
    async def complete_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeCompletion:
        """Return a tool call on the first turn and final text on continuation."""
        del route
        self.last_request = request
        if request.tool_results:
            return RuntimeCompletion(
                output_text='Tool says hello.',
                session_id=request.session_id,
                prompt_tokens=12,
                completion_tokens=3,
            )

        return RuntimeCompletion(
            output_text='Plan:',
            finish_reason='tool_calls',
            session_id='responses-tool-session',
            pending_tool_call=CanonicalToolCall(
                call_id='call_readme',
                name='read_file',
                arguments={'path': 'README.md'},
            ),
            prompt_tokens=9,
            completion_tokens=1,
        )

    @override
    async def stream_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeEventStream:
        """Emit a tool request on the first turn and final text after tool output."""
        del route
        self.last_request = request

        async def _events() -> AsyncIterator[SessionEvent]:
            """Yield tool-request or final-turn events depending on the turn state."""
            if request.tool_results:
                events = (
                    SessionEvent.from_dict(
                        {
                            'id': '00000000-0000-0000-0000-000000000121',
                            'timestamp': '2025-01-01T00:00:00Z',
                            'type': 'assistant.message_delta',
                            'data': {'deltaContent': 'Done'},
                        }
                    ),
                    SessionEvent.from_dict(
                        {
                            'id': '00000000-0000-0000-0000-000000000122',
                            'timestamp': '2025-01-01T00:00:00Z',
                            'type': 'assistant.turn_end',
                            'data': {
                                'reason': 'stop',
                                'inputTokens': 12,
                                'outputTokens': 3,
                            },
                        }
                    ),
                )
            else:
                events = (
                    SessionEvent.from_dict(
                        {
                            'id': '00000000-0000-0000-0000-000000000123',
                            'timestamp': '2025-01-01T00:00:00Z',
                            'type': 'assistant.message_delta',
                            'data': {'deltaContent': 'Plan'},
                        }
                    ),
                    SessionEvent.from_dict(
                        {
                            'id': '00000000-0000-0000-0000-000000000124',
                            'timestamp': '2025-01-01T00:00:00Z',
                            'type': 'external_tool.requested',
                            'data': {
                                'requestId': 'tool-request-1',
                                'toolName': 'read_file',
                                'toolCallId': 'call_readme',
                                'arguments': {'path': 'README.md'},
                            },
                        }
                    ),
                )

            for event in events:
                yield event

        return RuntimeEventStream(session_id='responses-tool-session', events=_events())


def _extract_completed_frame_data(*, payload: str) -> str:
    """Return the serialized ``response.completed`` SSE payload."""
    frames = parse_sse_frames(payload=payload)
    completed_frame = next(
        frame
        for frame in frames
        if '"type":"response.completed"' in frame.get('data', '')
    )
    return completed_frame['data']


@pytest.mark.asyncio
async def test_post_responses_returns_openai_compatible_payload() -> None:
    """Verify that the Responses route returns the expected non-streaming payload."""
    runtime = _FakeResponsesRuntime()
    payload: dict[str, object] = {
        'model': 'gpt-5.4',
        'instructions': 'Be terse',
        'input': [
            {
                'type': 'message',
                'role': 'developer',
                'content': [{'type': 'input_text', 'text': 'Use plain text'}],
            },
            {
                'type': 'message',
                'role': 'user',
                'content': [{'type': 'input_text', 'text': 'Hello'}],
            },
        ],
    }
    async with build_async_client(runtime=runtime) as client:
        response = await client.post(
            '/openai/v1/responses',
            json=payload,
        )

    payload = cast('dict[str, Any]', response.json())
    output = cast('list[dict[str, Any]]', payload['output'])
    content = cast('list[dict[str, Any]]', output[0]['content'])
    assert response.status_code == 200
    assert payload['object'] == 'response'
    assert payload['status'] == 'completed'
    assert payload['model'] == 'gpt-5.4'
    assert output[0]['type'] == 'message'
    assert content[0]['type'] == 'output_text'
    assert content[0]['text'] == 'Hello from the fake runtime.'
    assert payload['usage'] == {
        'input_tokens': 9,
        'output_tokens': 6,
        'total_tokens': 15,
    }
    assert runtime.last_request is not None
    assert [message.model_dump() for message in runtime.last_request.messages] == [
        {'role': 'system', 'content': 'Be terse'},
        {'role': 'system', 'content': 'Use plain text'},
        {'role': 'user', 'content': 'Hello'},
    ]


@pytest.mark.asyncio
async def test_post_responses_accepts_non_text_content_parts_without_422() -> None:
    """Verify that non-text content parts are ignored instead of rejected."""
    runtime = _FakeResponsesRuntime()
    payload: dict[str, object] = {
        'model': 'gpt-5.4',
        'input': [
            {
                'type': 'message',
                'role': 'user',
                'content': [
                    {'type': 'input_text', 'text': 'Summarize this attachment.'},
                    {
                        'type': 'input_image',
                        'image_url': 'https://example.com/image.png',
                    },
                    {'type': 'input_file', 'file_id': 'file-123'},
                ],
            }
        ],
    }
    async with build_async_client(runtime=runtime) as client:
        response = await client.post('/openai/v1/responses', json=payload)

    assert response.status_code == 200
    assert runtime.last_request is not None
    assert [message.model_dump() for message in runtime.last_request.messages] == [
        {'role': 'user', 'content': 'Summarize this attachment.'}
    ]


@pytest.mark.asyncio
async def test_post_responses_accepts_truncation_as_compatibility_field() -> None:
    """Verify that Responses requests accept the ``truncation`` field unchanged."""
    runtime = _FakeResponsesRuntime()
    payload: dict[str, object] = {
        'model': 'gpt-5.4',
        'input': 'Hello',
        'truncation': 'auto',
    }

    assert_payload_field_handling(
        surface=ProtocolSurface.OPENAI_RESPONSES,
        payload=payload,
        allowed=(FieldHandling.SUPPORTED, FieldHandling.ACCEPT_IGNORE),
    )

    async with build_async_client(runtime=runtime) as client:
        response = await client.post('/openai/v1/responses', json=payload)

    assert response.status_code == 200
    assert runtime.last_request is not None
    assert [message.model_dump() for message in runtime.last_request.messages] == [
        {'role': 'user', 'content': 'Hello'}
    ]


@pytest.mark.asyncio
async def test_post_responses_extracts_bearer_token() -> None:
    """Verify that auth headers map into the canonical runtime request."""
    runtime = _FakeResponsesRuntime()
    async with build_async_client(runtime=runtime) as client:
        response = await client.post(
            '/openai/v1/responses',
            headers={
                'Authorization': 'Bearer github-token-123',
            },
            json={
                'model': 'gpt-5.4',
                'input': 'Hello',
            },
        )

    assert response.status_code == 200
    assert runtime.last_request is not None
    assert runtime.last_request.runtime_auth_token == 'github-token-123'  # noqa: S105 - deterministic test token


@pytest.mark.asyncio
async def test_post_responses_fall_back_to_configured_runtime_token() -> None:
    """Verify that Responses requests use the configured runtime token when needed."""
    runtime = _FakeResponsesRuntime()
    async with build_async_client(
        runtime=runtime,
        settings=ProviderSettings(
            environment='test',
            runtime_auth_token='github-token-456',  # noqa: S106 - deterministic test token
        ),
    ) as client:
        response = await client.post(
            '/openai/v1/responses',
            json={
                'model': 'gpt-5.4',
                'input': 'Hello',
            },
        )

    assert response.status_code == 200
    assert runtime.last_request is not None
    assert runtime.last_request.runtime_auth_token == 'github-token-456'  # noqa: S105 - deterministic test token


@pytest.mark.asyncio
async def test_post_responses_prefer_request_auth_over_configured_runtime_token() -> (
    None
):
    """Verify that explicit Responses auth overrides the configured runtime token."""
    runtime = _FakeResponsesRuntime()
    async with build_async_client(
        runtime=runtime,
        settings=ProviderSettings(
            environment='test',
            runtime_auth_token='github-token-456',  # noqa: S106 - deterministic test token
        ),
    ) as client:
        response = await client.post(
            '/openai/v1/responses',
            headers={'Authorization': 'Bearer github-token-123'},
            json={
                'model': 'gpt-5.4',
                'input': 'Hello',
            },
        )

    assert response.status_code == 200
    assert runtime.last_request is not None
    assert runtime.last_request.runtime_auth_token == 'github-token-123'  # noqa: S105 - deterministic test token


@pytest.mark.asyncio
async def test_post_responses_streams_openai_compatible_sse_frames() -> None:
    """Verify that streaming Responses requests emit lifecycle SSE frames."""
    async with (
        build_async_client(runtime=_FakeResponsesRuntime()) as client,
        client.stream(
            'POST',
            '/openai/v1/responses',
            json={
                'model': 'gpt-5.4',
                'stream': True,
                'input': 'Hello',
            },
        ) as response,
    ):
        payload = ''.join([chunk async for chunk in response.aiter_text()])

    completed_frame_data = _extract_completed_frame_data(payload=payload)
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/event-stream')
    assert '"type":"response.created"' in payload
    assert '"type":"response.output_text.delta"' in payload
    assert '"delta":"Hello"' in payload
    assert '"type":"response.completed"' in payload
    assert (
        '"usage":{"input_tokens":9,"output_tokens":6,"total_tokens":15}'
        in completed_frame_data
    )


@pytest.mark.asyncio
async def test_post_responses_streaming_deduplicates_final_aggregate_message() -> None:
    """Verify that aggregate assistant.message events do not duplicate streamed text."""
    async with (
        build_async_client(runtime=_FakeResponsesAggregateRuntime()) as client,
        client.stream(
            'POST',
            '/openai/v1/responses',
            json={
                'model': 'gpt-5.4',
                'stream': True,
                'input': 'Hello',
            },
        ) as response,
    ):
        payload = ''.join([chunk async for chunk in response.aiter_text()])

    assert response.status_code == 200
    assert payload.count('"type":"response.output_text.delta"') == 1
    assert '"text":"HelloHello"' not in payload


@pytest.mark.asyncio
async def test_post_responses_streaming_supports_function_call_continuation() -> None:
    """Verify that Responses streams can pause on a tool call and continue later."""
    runtime = _FakeResponsesToolRuntime()
    first_request_body: dict[str, object] = {
        'model': 'gpt-5.4',
        'stream': True,
        'input': 'Open the readme',
        'tools': [
            {
                'type': 'function',
                'function': {
                    'name': 'read_file',
                    'description': 'Read one file.',
                    'parameters': {'type': 'object'},
                },
            }
        ],
    }
    async with build_async_client(runtime=runtime) as client:
        async with client.stream(
            'POST',
            '/openai/v1/responses',
            json=first_request_body,
        ) as response:
            first_payload = ''.join([chunk async for chunk in response.aiter_text()])

        first_completed_payload = cast(
            'dict[str, Any]',
            json.loads(_extract_completed_frame_data(payload=first_payload)),
        )
        response_id = cast('str', first_completed_payload['response']['id'])

        assert response.status_code == 200
        assert '"type":"response.output_text.done"' in first_payload
        assert '"type":"function_call"' in first_payload
        assert '"call_id":"call_readme"' in first_payload

        follow_up = await client.post(
            '/openai/v1/responses',
            json={
                'model': 'gpt-5.4',
                'previous_response_id': response_id,
                'input': [
                    {
                        'type': 'function_call_output',
                        'call_id': 'call_readme',
                        'output': 'README contents',
                    }
                ],
            },
        )

    follow_up_payload = cast('dict[str, Any]', follow_up.json())
    output = cast('list[dict[str, Any]]', follow_up_payload['output'])
    assert follow_up.status_code == 200
    assert output[0]['content'][0]['text'] == 'Tool says hello.'
    assert runtime.last_request is not None
    assert runtime.last_request.session_id == 'responses-tool-session'
    assert [result.model_dump() for result in runtime.last_request.tool_results] == [
        {
            'call_id': 'call_readme',
            'output_text': 'README contents',
            'is_error': False,
            'error_text': None,
        }
    ]
