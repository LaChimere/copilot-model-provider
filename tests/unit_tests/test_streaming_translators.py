"""Unit tests for SDK-event translation in the streaming transport slice."""

from __future__ import annotations

from typing import Any

import pytest
from copilot.generated.session_events import ErrorClass, SessionEvent

import copilot_model_provider.streaming.translators as streaming_translators
from copilot_model_provider.streaming.events import (
    AssistantTextDeltaEvent,
    AssistantTurnCompleteEvent,
    StreamFinishReason,
    StreamingErrorEvent,
)
from copilot_model_provider.streaming.translators import (
    build_finish_chunk,
    build_text_delta_chunk,
    translate_session_event,
    translate_session_event_to_openai_chunks,
)


def _build_session_event(
    *,
    event_type: str,
    data: dict[str, Any] | None = None,
    event_id: str = '00000000-0000-0000-0000-000000000001',
) -> SessionEvent:
    """Build a deterministic SDK event for translator unit tests."""
    return SessionEvent.from_dict(
        {
            'id': event_id,
            'timestamp': '2025-01-01T00:00:00Z',
            'type': event_type,
            'data': data or {},
        }
    )


def test_translate_session_event_maps_message_delta_to_text_delta() -> None:
    """Verify that assistant delta events become canonical text-delta events."""
    stream_event = translate_session_event(
        event=_build_session_event(
            event_type='assistant.message_delta',
            data={'deltaContent': 'Hello'},
        )
    )

    assert stream_event == AssistantTextDeltaEvent(text='Hello')


def test_translate_session_event_uses_full_message_content_when_needed() -> None:
    """Verify that full assistant message events are still translated to text."""
    stream_event = translate_session_event(
        event=_build_session_event(
            event_type='assistant.message',
            data={'content': 'Whole message'},
        )
    )

    assert stream_event == AssistantTextDeltaEvent(text='Whole message')


@pytest.mark.parametrize(
    ('reason', 'expected'),
    [
        ('max_tokens', 'length'),
        ('length', 'length'),
        ('content_filter', 'content_filter'),
        ('tool_calls', 'tool_calls'),
        ('unknown', 'stop'),
        (None, 'stop'),
    ],
)
def test_translate_session_event_normalizes_turn_end_finish_reasons(
    reason: str | None,
    expected: StreamFinishReason,
) -> None:
    """Verify that turn-end reasons are normalized into OpenAI finish reasons."""
    stream_event = translate_session_event(
        event=_build_session_event(
            event_type='assistant.turn_end',
            data={'reason': reason},
        )
    )

    assert stream_event == AssistantTurnCompleteEvent(finish_reason=expected)


def test_translate_session_event_preserves_turn_end_token_counts() -> None:
    """Verify that turn-end token accounting is retained for downstream usage."""
    stream_event = translate_session_event(
        event=_build_session_event(
            event_type='assistant.turn_end',
            data={
                'reason': 'stop',
                'inputTokens': 9,
                'outputTokens': 6,
            },
        )
    )

    assert stream_event == AssistantTurnCompleteEvent(
        finish_reason='stop',
        prompt_tokens=9,
        completion_tokens=6,
    )


def test_translate_session_event_maps_session_errors_to_canonical_error_events() -> (
    None
):
    """Verify that stream errors remain explicit for convergence handling."""
    stream_event = translate_session_event(
        event=_build_session_event(
            event_type='session.error',
            data={'errorType': 'runtime_crash', 'message': 'stream failed'},
        )
    )

    assert stream_event == StreamingErrorEvent(
        code='runtime_crash',
        message='stream failed',
    )


def test_translate_session_event_falls_back_for_whitespace_only_error_type() -> None:
    """Verify that blank-looking error codes normalize to the default fallback."""
    stream_event = translate_session_event(
        event=_build_session_event(
            event_type='session.error',
            data={'errorType': ' \t ', 'message': 'stream failed'},
        )
    )

    assert stream_event == StreamingErrorEvent(
        code='session_error',
        message='stream failed',
    )


@pytest.mark.parametrize(
    ('data', 'nested_error'),
    [
        ({'message': ' \t '}, None),
        ({}, ' \t '),
        ({'message': ' \t '}, ErrorClass(message=' \t ')),
    ],
)
def test_translate_session_event_falls_back_for_whitespace_only_error_messages(
    data: dict[str, Any],
    nested_error: ErrorClass | str | None,
) -> None:
    """Verify that blank-looking error messages normalize to the default fallback."""
    event = _build_session_event(event_type='session.error', data=data)
    event.data.error = nested_error

    stream_event = translate_session_event(event=event)

    assert stream_event == StreamingErrorEvent(
        code='session_error',
        message='Copilot runtime reported a streaming session error.',
    )


def test_translate_session_event_ignores_non_streaming_events() -> None:
    """Verify that unrelated SDK events do not leak into the public chat stream."""
    stream_event = translate_session_event(
        event=_build_session_event(event_type='session.idle')
    )

    assert stream_event is None


def test_translate_session_event_to_openai_chunks_emits_role_on_first_chunk() -> None:
    """Verify that chunk translation can attach the assistant role when requested."""
    chunks = translate_session_event_to_openai_chunks(
        event=_build_session_event(
            event_type='assistant.streaming_delta',
            data={'deltaContent': 'Hello'},
        ),
        completion_id='chatcmpl-stream-1',
        model='default',
        emit_role=True,
        created=1_735_689_600,
    )

    assert len(chunks) == 1
    payload = chunks[0].model_dump(exclude_none=True)
    assert payload['choices'][0]['delta'] == {
        'role': 'assistant',
        'content': 'Hello',
    }


def test_translate_session_event_to_openai_chunks_raises_for_stream_errors() -> None:
    """Verify that stream errors must be handled explicitly by integration code."""
    with pytest.raises(ValueError, match='do not have an OpenAI chat chunk'):
        translate_session_event_to_openai_chunks(
            event=_build_session_event(
                event_type='session.error',
                data={'message': 'stream failed'},
            ),
            completion_id='chatcmpl-stream-1',
            model='default',
        )


@pytest.mark.parametrize(
    ('builder', 'kwargs'),
    [
        (
            build_text_delta_chunk,
            {'text': 'Hello', 'role': 'assistant'},
        ),
        (
            build_finish_chunk,
            {},
        ),
    ],
)
def test_chunk_builders_normalize_zero_created_timestamps(
    monkeypatch: pytest.MonkeyPatch,
    builder: Any,
    kwargs: dict[str, Any],
) -> None:
    """Verify that zero-valued chunk timestamps fall back to the current time."""
    monkeypatch.setattr(streaming_translators, 'time', lambda: 1_735_689_600.9)

    chunk = builder(
        completion_id='chatcmpl-stream-1',
        model='default',
        created=0,
        **kwargs,
    )

    assert chunk.created == 1_735_689_600
