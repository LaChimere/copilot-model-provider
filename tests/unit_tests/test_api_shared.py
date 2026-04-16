"""Unit tests for shared HTTP streaming helpers."""

from __future__ import annotations

from copilot.generated.session_events import SessionEvent

from copilot_model_provider.api.shared import should_skip_aggregated_assistant_message


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
