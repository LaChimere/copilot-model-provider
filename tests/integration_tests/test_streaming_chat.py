"""Integration tests for the owned streaming translation and SSE pipeline."""

from __future__ import annotations

import json
from typing import Any

from copilot.generated.session_events import SessionEvent

from copilot_model_provider.streaming.sse import iter_openai_chat_sse
from copilot_model_provider.streaming.translators import (
    translate_session_event_to_openai_chunks,
)


def _build_session_event(
    *,
    event_type: str,
    data: dict[str, Any] | None = None,
    event_id: str,
) -> SessionEvent:
    """Build a deterministic SDK event for streaming integration tests."""
    return SessionEvent.from_dict(
        {
            'id': event_id,
            'timestamp': '2025-01-01T00:00:00Z',
            'type': event_type,
            'data': data or {},
        }
    )


def _decode_sse_payload(frame: str) -> dict[str, Any]:
    """Decode an SSE JSON frame emitted by the streaming transport helpers."""
    return json.loads(frame.removeprefix('data: ').strip())


def test_streaming_chat_pipeline_translates_sdk_events_into_sse_frames() -> None:
    """Verify that the owned streaming helpers produce OpenAI-compatible frames."""
    events = [
        _build_session_event(
            event_type='assistant.message_delta',
            data={'deltaContent': 'Hello'},
            event_id='00000000-0000-0000-0000-000000000001',
        ),
        _build_session_event(
            event_type='assistant.streaming_delta',
            data={'deltaContent': ' world'},
            event_id='00000000-0000-0000-0000-000000000002',
        ),
        _build_session_event(
            event_type='assistant.turn_end',
            data={'reason': 'stop'},
            event_id='00000000-0000-0000-0000-000000000003',
        ),
    ]

    chunks = [
        *translate_session_event_to_openai_chunks(
            event=events[0],
            completion_id='chatcmpl-stream-1',
            model='default',
            emit_role=True,
            created=1_735_689_600,
        ),
        *translate_session_event_to_openai_chunks(
            event=events[1],
            completion_id='chatcmpl-stream-1',
            model='default',
            created=1_735_689_600,
        ),
        *translate_session_event_to_openai_chunks(
            event=events[2],
            completion_id='chatcmpl-stream-1',
            model='default',
            created=1_735_689_600,
        ),
    ]
    frames = list(iter_openai_chat_sse(chunks=chunks))

    assert len(frames) == 4
    assert _decode_sse_payload(frames[0])['choices'][0]['delta'] == {
        'role': 'assistant',
        'content': 'Hello',
    }
    assert _decode_sse_payload(frames[1])['choices'][0]['delta'] == {
        'content': ' world'
    }
    assert _decode_sse_payload(frames[2])['choices'][0]['finish_reason'] == 'stop'
    assert frames[3] == 'data: [DONE]\n\n'
