"""Shared helpers for contract-level compatibility assertions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from copilot_model_provider.core.compat import (
    FieldHandling,
    ProtocolSurface,
    classify_request_fields,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence


def assert_payload_field_handling(
    *,
    surface: ProtocolSurface,
    payload: Mapping[str, object],
    allowed: Sequence[FieldHandling],
) -> None:
    """Assert that every field in a request payload has an allowed handling rule.

    Args:
        surface: Public request surface whose compatibility rules should apply.
        payload: Request-like mapping to classify.
        allowed: Handling values considered valid for this assertion.

    """
    classified_fields = classify_request_fields(surface=surface, payload=payload)
    disallowed_fields = {
        field_name: rule.handling.value
        for field_name, rule in classified_fields.items()
        if rule.handling not in allowed
    }
    assert disallowed_fields == {}


def parse_sse_frames(*, payload: str) -> list[dict[str, str]]:
    """Parse a raw SSE payload into frame dictionaries for assertions.

    Args:
        payload: Concatenated SSE text returned by a streaming HTTP response.

    Returns:
        A list of frame dictionaries. Each dictionary contains the raw SSE fields
        present in one frame, with repeated ``data:`` lines joined by newlines.

    """
    parsed_frames: list[dict[str, str]] = []
    for raw_frame in payload.strip().split('\n\n'):
        if not raw_frame.strip():
            continue

        frame: dict[str, str] = {}
        data_lines: list[str] = []
        for raw_line in raw_frame.splitlines():
            key, _, value = raw_line.partition(':')
            normalized_value = value.lstrip()
            if key == 'data':
                data_lines.append(normalized_value)
                continue
            frame[key] = normalized_value

        if data_lines:
            frame['data'] = '\n'.join(data_lines)
        parsed_frames.append(frame)

    return parsed_frames


def assert_sse_event_sequence(
    *,
    frames: Iterable[dict[str, str]],
    expected_events: Sequence[str],
) -> None:
    """Assert that parsed SSE frames include the expected named event sequence.

    Args:
        frames: Parsed SSE frame dictionaries, typically from ``parse_sse_frames``.
        expected_events: Ordered event names that must appear in the parsed stream.

    """
    actual_events = [frame['event'] for frame in frames if 'event' in frame]
    assert actual_events == list(expected_events)
