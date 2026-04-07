"""Unit tests for shared HTTP helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from copilot.generated.session_events import SessionEvent

from copilot_model_provider.api.shared import (
    iter_canonical_runtime_stream_events,
    normalize_anthropic_gateway_headers,
)
from copilot_model_provider.streaming.events import (
    AssistantTextDeltaEvent,
    AssistantTurnCompleteEvent,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from copilot_model_provider.runtimes.protocols import RuntimeEventStream


def _build_session_event(
    *,
    event_type: str,
    data: dict[str, object] | None = None,
    event_id: str = '00000000-0000-0000-0000-000000000001',
) -> SessionEvent:
    """Build a deterministic SDK event for shared-helper tests."""
    return SessionEvent.from_dict(
        {
            'id': event_id,
            'timestamp': '2025-01-01T00:00:00Z',
            'type': event_type,
            'data': data or {},
        }
    )


def _build_runtime_stream(*, events: list[SessionEvent]) -> RuntimeEventStream:
    """Build a minimal runtime stream for shared-helper tests."""

    async def _iter_events() -> AsyncIterator[SessionEvent]:
        """Yield the configured SDK events in order."""
        for event in events:
            yield event

    from copilot_model_provider.runtimes.protocols import RuntimeEventStream

    return RuntimeEventStream(session_id=None, events=_iter_events())


@pytest.mark.asyncio
async def test_iter_canonical_runtime_stream_events_deduplicates_aggregate_message() -> (
    None
):
    """Verify that a later aggregate assistant message is skipped after deltas."""
    runtime_stream = _build_runtime_stream(
        events=[
            _build_session_event(
                event_type='assistant.message_delta',
                data={'deltaContent': 'Hello'},
                event_id='00000000-0000-0000-0000-000000000011',
            ),
            _build_session_event(
                event_type='assistant.message',
                data={'content': 'Hello'},
                event_id='00000000-0000-0000-0000-000000000012',
            ),
            _build_session_event(
                event_type='assistant.turn_end',
                data={'reason': 'stop'},
                event_id='00000000-0000-0000-0000-000000000013',
            ),
        ]
    )

    events = [
        event
        async for event in iter_canonical_runtime_stream_events(
            runtime_stream=runtime_stream
        )
    ]

    assert events == [
        AssistantTextDeltaEvent(text='Hello'),
        AssistantTurnCompleteEvent(finish_reason='stop'),
    ]


def test_normalize_anthropic_gateway_headers_collapses_blank_values() -> None:
    """Verify that optional Claude gateway headers normalize blank values to None."""
    headers = normalize_anthropic_gateway_headers(
        anthropic_version_header=' 2023-06-01 ',
        anthropic_beta_header=' ',
        claude_code_session_id_header=' session-123 ',
    )

    assert headers.anthropic_version == '2023-06-01'
    assert headers.anthropic_beta is None
    assert headers.claude_code_session_id == 'session-123'
