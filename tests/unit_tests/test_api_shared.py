"""Unit tests for shared HTTP streaming helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from copilot.generated.session_events import SessionEvent

from copilot_model_provider.api.shared import (
    iter_canonical_runtime_stream_events,
    should_skip_aggregated_assistant_message,
)
from copilot_model_provider.runtimes.protocols import RuntimeEventStream
from copilot_model_provider.streaming.events import AssistantTextDeltaEvent

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def _build_session_event(*, event_type: str, data: dict[str, object]) -> SessionEvent:
    """Build a deterministic session event for shared-helper tests."""
    return SessionEvent.from_dict(
        {
            'id': '00000000-0000-0000-0000-000000000001',
            'timestamp': '2025-01-01T00:00:00Z',
            'type': event_type,
            'data': data,
        }
    )


def test_should_skip_aggregated_assistant_message_skips_text_only_message() -> None:
    """Verify that text-only aggregate assistant messages are skipped after deltas."""
    assert (
        should_skip_aggregated_assistant_message(
            event=_build_session_event(
                event_type='assistant.message',
                data={'content': 'Hello'},
            ),
            saw_text_delta=True,
        )
        is True
    )


def test_should_skip_aggregated_assistant_message_keeps_tool_request_message() -> None:
    """Verify that aggregate assistant messages with tool requests are still processed."""
    assert (
        should_skip_aggregated_assistant_message(
            event=_build_session_event(
                event_type='assistant.message',
                data={
                    'content': 'Hello',
                    'toolRequests': [
                        {
                            'toolCallId': 'call_readme',
                            'name': 'read_file',
                            'arguments': {'path': 'README.md'},
                        }
                    ],
                },
            ),
            saw_text_delta=True,
        )
        is False
    )


@pytest.mark.asyncio
async def test_iter_canonical_runtime_stream_events_keeps_tool_requests_without_duplicate_text() -> (
    None
):
    """Verify that aggregate tool metadata survives after prior text deltas."""

    async def _events() -> AsyncIterator[SessionEvent]:
        """Yield one delta followed by a mixed aggregate assistant message."""
        for event in (
            _build_session_event(
                event_type='assistant.message_delta',
                data={'deltaContent': 'Hello'},
            ),
            _build_session_event(
                event_type='assistant.message',
                data={
                    'content': 'Hello',
                    'toolRequests': [
                        {
                            'toolCallId': 'call_readme',
                            'name': 'read_file',
                            'arguments': {'path': 'README.md'},
                        }
                    ],
                },
            ),
            _build_session_event(
                event_type='assistant.turn_end',
                data={'reason': 'tool_calls'},
            ),
        ):
            yield event

    runtime_stream = RuntimeEventStream(session_id='session-1', events=_events())
    stream_events = [
        event
        async for event in iter_canonical_runtime_stream_events(
            runtime_stream=runtime_stream
        )
    ]

    assert [type(event).__name__ for event in stream_events] == [
        'AssistantTextDeltaEvent',
        'ToolCallRequestedEvent',
        'AssistantTurnCompleteEvent',
    ]
    assert stream_events[0] == AssistantTextDeltaEvent(text='Hello')
