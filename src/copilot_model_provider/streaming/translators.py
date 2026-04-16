"""Translators between Copilot SDK events and OpenAI-compatible chunks."""

from __future__ import annotations

from time import time
from typing import Literal

from copilot.generated.session_events import SessionEvent, SessionEventType

from copilot_model_provider.core.models import CanonicalToolCall
from copilot_model_provider.streaming.events import (
    AssistantTextDeltaEvent,
    AssistantTurnCompleteEvent,
    AssistantUsageEvent,
    CanonicalStreamingEvent,
    OpenAIChatCompletionChunk,
    OpenAIChatCompletionChunkChoice,
    OpenAIChatCompletionChunkDelta,
    StreamFinishReason,
    StreamingErrorEvent,
    ToolCallRequestedEvent,
)


def build_text_delta_chunk(
    *,
    completion_id: str,
    model: str,
    text: str,
    role: Literal['assistant'] | None = None,
    created: int | None = None,
    choice_index: int = 0,
) -> OpenAIChatCompletionChunk:
    """Build an OpenAI-compatible chunk for assistant text deltas.

    Args:
        completion_id: Stable response identifier reused across stream frames.
        model: Public model alias exposed by the compatibility layer.
        text: Assistant delta text to expose in this chunk.
        role: Optional role field for the first chunk of a stream.
        created: Optional Unix timestamp. When omitted or non-positive, the
            current time is used.
        choice_index: Choice position inside the OpenAI response envelope.

    Returns:
        An OpenAI-compatible streaming chunk containing assistant delta text.

    """
    return _build_chunk(
        completion_id=completion_id,
        model=model,
        created=created,
        choice_index=choice_index,
        delta=OpenAIChatCompletionChunkDelta(role=role, content=text),
        finish_reason=None,
    )


def build_finish_chunk(
    *,
    completion_id: str,
    model: str,
    finish_reason: StreamFinishReason = 'stop',
    created: int | None = None,
    choice_index: int = 0,
) -> OpenAIChatCompletionChunk:
    """Build the terminal OpenAI-compatible chunk for a completed assistant turn.

    Args:
        completion_id: Stable response identifier reused across stream frames.
        model: Public model alias exposed by the compatibility layer.
        finish_reason: OpenAI-compatible reason describing why the turn ended.
        created: Optional Unix timestamp. When omitted or non-positive, the
            current time is used.
        choice_index: Choice position inside the OpenAI response envelope.

    Returns:
        An OpenAI-compatible terminal chunk with an empty delta payload.

    """
    return _build_chunk(
        completion_id=completion_id,
        model=model,
        created=created,
        choice_index=choice_index,
        delta=OpenAIChatCompletionChunkDelta(),
        finish_reason=finish_reason,
    )


def translate_session_event(*, event: SessionEvent) -> CanonicalStreamingEvent | None:
    """Translate a raw Copilot SDK session event into a canonical stream event.

    Args:
        event: Copilot SDK event emitted by a streaming session.

    Returns:
        A canonical streaming event when the SDK event affects the public chat
        stream, or ``None`` when the event is not part of the OpenAI-compatible
        transport surface.

    """
    text_event = _translate_text_event(event=event)
    if text_event is not None:
        return text_event

    turn_end_event = _translate_turn_end_event(event=event)
    if turn_end_event is not None:
        return turn_end_event

    usage_event = _translate_usage_event(event=event)
    if usage_event is not None:
        return usage_event

    tool_event = _translate_tool_requested_event(event=event)
    if tool_event is not None:
        return tool_event

    if event.type == SessionEventType.SESSION_ERROR:
        data = event.data
        return StreamingErrorEvent(
            code=_normalize_error_field(value=data.error_type) or 'session_error',
            message=_extract_error_message(event=event),
        )

    return None


def translate_stream_event_to_openai_chunks(
    *,
    event: CanonicalStreamingEvent,
    completion_id: str,
    model: str,
    emit_role: bool = False,
    created: int | None = None,
    choice_index: int = 0,
) -> tuple[OpenAIChatCompletionChunk, ...]:
    """Translate a canonical stream event into OpenAI-compatible chat chunks.

    Args:
        event: Canonical event produced by ``translate_session_event``.
        completion_id: Stable response identifier reused across stream frames.
        model: Public model alias exposed by the compatibility layer.
        emit_role: Whether to include ``assistant`` in the chunk delta.
        created: Optional Unix timestamp. When omitted or non-positive, the
            current time is used.
        choice_index: Choice position inside the OpenAI response envelope.

    Returns:
        A tuple containing zero or more OpenAI-compatible chat chunks.

    Raises:
        ValueError: If the provided canonical event is a stream error that must
            be handled explicitly by the convergence owner.

    """
    if isinstance(event, AssistantTextDeltaEvent):
        return (
            build_text_delta_chunk(
                completion_id=completion_id,
                model=model,
                text=event.text,
                role='assistant' if emit_role else None,
                created=created,
                choice_index=choice_index,
            ),
        )

    if isinstance(event, AssistantTurnCompleteEvent):
        return (
            build_finish_chunk(
                completion_id=completion_id,
                model=model,
                finish_reason=event.finish_reason,
                created=created,
                choice_index=choice_index,
            ),
        )

    if isinstance(event, ToolCallRequestedEvent):
        return ()

    message = 'Streaming error events do not have an OpenAI chat chunk representation.'
    raise ValueError(message)


def _translate_text_event(*, event: SessionEvent) -> AssistantTextDeltaEvent | None:
    """Translate SDK text-bearing events into canonical text deltas."""
    data = event.data
    if event.type in {
        SessionEventType.ASSISTANT_MESSAGE_DELTA,
        SessionEventType.ASSISTANT_STREAMING_DELTA,
    }:
        text = _first_non_empty_text(data.delta_content, data.content)
        return AssistantTextDeltaEvent(text=text) if text is not None else None

    if event.type == SessionEventType.ASSISTANT_MESSAGE:
        text = _first_non_empty_text(data.content, data.transformed_content)
        return AssistantTextDeltaEvent(text=text) if text is not None else None

    return None


def _translate_turn_end_event(
    *, event: SessionEvent
) -> AssistantTurnCompleteEvent | None:
    """Translate SDK turn-end events into canonical completion events."""
    if event.type != SessionEventType.ASSISTANT_TURN_END:
        return None

    data = event.data
    return AssistantTurnCompleteEvent(
        finish_reason=_normalize_finish_reason(reason=data.reason),
        prompt_tokens=_normalize_optional_non_negative_int(
            value=getattr(data, 'input_tokens', None)
        ),
        completion_tokens=_normalize_optional_non_negative_int(
            value=getattr(data, 'output_tokens', None)
        ),
    )


def _translate_usage_event(*, event: SessionEvent) -> AssistantUsageEvent | None:
    """Translate SDK usage events into canonical usage metadata."""
    if event.type != SessionEventType.ASSISTANT_USAGE:
        return None

    data = event.data
    prompt_tokens = _normalize_optional_non_negative_int(
        value=getattr(data, 'input_tokens', None)
    )
    completion_tokens = _normalize_optional_non_negative_int(
        value=getattr(data, 'output_tokens', None)
    )
    if prompt_tokens is None and completion_tokens is None:
        return None

    return AssistantUsageEvent(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


def _translate_tool_requested_event(
    *, event: SessionEvent
) -> ToolCallRequestedEvent | None:
    """Translate SDK external-tool events into canonical tool-call requests."""
    if event.type != SessionEventType.EXTERNAL_TOOL_REQUESTED:
        return None

    data = event.data
    tool_call_id = _normalize_error_field(value=getattr(data, 'tool_call_id', None))
    tool_name = _normalize_error_field(value=getattr(data, 'tool_name', None))
    if tool_call_id is None or tool_name is None:
        return None

    return ToolCallRequestedEvent(
        tool_call=CanonicalToolCall(
            call_id=tool_call_id,
            name=tool_name,
            arguments=getattr(data, 'arguments', None),
        )
    )


def translate_session_event_to_openai_chunks(
    *,
    event: SessionEvent,
    completion_id: str,
    model: str,
    emit_role: bool = False,
    created: int | None = None,
    choice_index: int = 0,
) -> tuple[OpenAIChatCompletionChunk, ...]:
    """Translate one Copilot SDK event into OpenAI-compatible chat chunks.

    Args:
        event: Copilot SDK event emitted by a streaming session.
        completion_id: Stable response identifier reused across stream frames.
        model: Public model alias exposed by the compatibility layer.
        emit_role: Whether to include ``assistant`` in the chunk delta.
        created: Optional Unix timestamp. When omitted or non-positive, the
            current time is used.
        choice_index: Choice position inside the OpenAI response envelope.

    Returns:
        A tuple of OpenAI-compatible chunks derived from the SDK event. Irrelevant
        SDK events produce an empty tuple.

    Raises:
        ValueError: If the SDK event represents a stream error that must be
            handled outside the chunk translation path.

    """
    stream_event = translate_session_event(event=event)
    if stream_event is None:
        return ()

    return translate_stream_event_to_openai_chunks(
        event=stream_event,
        completion_id=completion_id,
        model=model,
        emit_role=emit_role,
        created=created,
        choice_index=choice_index,
    )


def _build_chunk(
    *,
    completion_id: str,
    model: str,
    created: int | None,
    choice_index: int,
    delta: OpenAIChatCompletionChunkDelta,
    finish_reason: StreamFinishReason | None,
) -> OpenAIChatCompletionChunk:
    """Build a single OpenAI-compatible chunk with shared metadata fields."""
    return OpenAIChatCompletionChunk(
        id=completion_id,
        created=_normalize_chunk_timestamp(created=created),
        model=model,
        choices=[
            OpenAIChatCompletionChunkChoice(
                index=choice_index,
                delta=delta,
                finish_reason=finish_reason,
            )
        ],
    )


def _normalize_finish_reason(*, reason: str | None) -> StreamFinishReason:
    """Normalize Copilot runtime reasons into OpenAI-compatible finish reasons."""
    if reason in {'max_tokens', 'length'}:
        return 'length'
    if reason == 'content_filter':
        return 'content_filter'
    if reason == 'tool_calls':
        return 'tool_calls'
    return 'stop'


def _first_non_empty_text(*values: object | None) -> str | None:
    """Return the first non-empty string value from a list of SDK fields."""
    for value in values:
        if isinstance(value, str) and value:
            return value

    return None


def _extract_error_message(*, event: SessionEvent) -> str:
    """Extract a stable human-readable message from a stream error event."""
    data = event.data
    nested_error = data.error
    normalized_nested_error = (
        _normalize_error_field(value=nested_error)
        if isinstance(nested_error, str)
        else None
    )
    if normalized_nested_error is not None:
        return normalized_nested_error

    nested_message = _normalize_error_field(
        value=getattr(nested_error, 'message', None)
    )
    if nested_message is not None:
        return nested_message

    message = _normalize_error_field(value=data.message)
    if message is not None:
        return message

    return 'Copilot runtime reported a streaming session error.'


def _normalize_error_field(*, value: str | None) -> str | None:
    """Return stripped error metadata when it contains non-whitespace text."""
    if value is None:
        return None

    normalized = value.strip()
    if not normalized:
        return None

    return normalized


def _normalize_chunk_timestamp(*, created: int | None) -> int:
    """Return a usable Unix timestamp for chunk metadata."""
    if created is None or created <= 0:
        return int(time())

    return created


def _normalize_optional_non_negative_int(
    *,
    value: int | float | str | None,
) -> int | None:
    """Normalize optional non-negative numeric metadata from SDK events.

    Args:
        value: Raw value read from the SDK event payload.

    Returns:
        The integer form of ``value`` when it is present and non-negative,
        otherwise ``None``.

    """
    if value is None:
        return None

    normalized_value = int(value)
    if normalized_value < 0:
        return None

    return normalized_value
