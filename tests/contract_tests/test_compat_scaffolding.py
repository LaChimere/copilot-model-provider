"""Contract-facing tests for compatibility scaffolding helpers."""

from __future__ import annotations

from copilot_model_provider.core.compat import FieldHandling, ProtocolSurface
from tests.contract_tests.helpers import (
    assert_payload_field_handling,
    assert_sse_event_sequence,
    parse_sse_frames,
)


def test_payload_field_handling_covers_current_request_surfaces() -> None:
    """Verify that shipped request payloads are classified by the shared registry."""
    assert_payload_field_handling(
        surface=ProtocolSurface.OPENAI_CHAT_COMPLETIONS,
        payload={
            'model': 'gpt-5.4',
            'messages': [{'role': 'user', 'content': 'Hello'}],
            'stream': True,
        },
        allowed=(FieldHandling.SUPPORTED,),
    )
    assert_payload_field_handling(
        surface=ProtocolSurface.OPENAI_RESPONSES,
        payload={
            'model': 'gpt-5.4',
            'input': 'Hello',
            'instructions': 'Be terse',
            'stream': True,
            'store': False,
            'tools': [],
        },
        allowed=(FieldHandling.SUPPORTED, FieldHandling.ACCEPT_IGNORE),
    )
    assert_payload_field_handling(
        surface=ProtocolSurface.ANTHROPIC_MESSAGES,
        payload={
            'model': 'claude-sonnet-4-20250514',
            'messages': [{'role': 'user', 'content': 'Hello'}],
            'system': 'You are terse.',
            'stream': True,
            'max_tokens': 128,
            'metadata': {'source': 'claude-code'},
        },
        allowed=(FieldHandling.SUPPORTED, FieldHandling.ACCEPT_IGNORE),
    )


def test_parse_sse_frames_extracts_named_event_sequence() -> None:
    """Verify that the shared SSE parser exposes named event ordering."""
    frames = parse_sse_frames(
        payload=(
            'event: message_start\n'
            'data: {"type":"message_start"}\n\n'
            'event: content_block_delta\n'
            'data: {"type":"content_block_delta"}\n\n'
            'event: message_stop\n'
            'data: {"type":"message_stop"}\n\n'
        )
    )

    assert_sse_event_sequence(
        frames=frames,
        expected_events=(
            'message_start',
            'content_block_delta',
            'message_stop',
        ),
    )
    assert frames[1]['data'] == '{"type":"content_block_delta"}'
