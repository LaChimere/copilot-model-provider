"""Translation helpers for the Anthropic-compatible northbound API surface."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from copilot_model_provider.core.models import (
    AnthropicContentBlockDeltaEvent,
    AnthropicContentBlockStartEvent,
    AnthropicContentBlockStopEvent,
    AnthropicCountTokensResponse,
    AnthropicMessageDelta,
    AnthropicMessageDeltaEvent,
    AnthropicMessageInput,
    AnthropicMessageResponse,
    AnthropicMessagesCountTokensRequest,
    AnthropicMessagesCreateRequest,
    AnthropicMessageStartEvent,
    AnthropicMessageStopEvent,
    AnthropicModelInfo,
    AnthropicModelListResponse,
    AnthropicStopReason,
    AnthropicTextContentBlock,
    AnthropicTextDelta,
    AnthropicUsage,
    CanonicalChatMessage,
    CanonicalChatRequest,
    OpenAIModelCard,
    OpenAIModelListResponse,
    RuntimeCompletion,
)

type AnthropicTokenCountableRequest = (
    AnthropicMessagesCreateRequest | AnthropicMessagesCountTokensRequest
)

_DISPLAY_NAME_ACRONYM_MAX_LENGTH = 3


def normalize_anthropic_messages_request(
    *,
    request: AnthropicMessagesCreateRequest,
    request_id: str | None = None,
    runtime_auth_token: str | None = None,
) -> CanonicalChatRequest:
    """Normalize an Anthropic Messages request into the canonical provider shape."""
    messages: list[CanonicalChatMessage] = []
    messages.extend(_normalize_anthropic_system_blocks(value=request.system))
    messages.extend(_normalize_anthropic_messages(value=request.messages))
    return CanonicalChatRequest(
        request_id=request_id,
        runtime_auth_token=runtime_auth_token,
        model_id=request.model,
        messages=messages,
        stream=request.stream,
    )


def build_anthropic_message_response_from_completion(
    *,
    request: AnthropicMessagesCreateRequest,
    completion: RuntimeCompletion,
    message_id: str,
) -> AnthropicMessageResponse:
    """Translate a runtime completion into a minimal Anthropic Messages payload."""
    return build_anthropic_message_response_from_text(
        model=request.model,
        output_text=completion.output_text,
        message_id=message_id,
        usage=build_anthropic_usage(
            prompt_tokens=completion.prompt_tokens,
            completion_tokens=completion.completion_tokens,
        ),
    )


def build_anthropic_count_tokens_response(
    *,
    request: AnthropicMessagesCountTokensRequest,
) -> AnthropicCountTokensResponse:
    """Build a minimal Anthropic count-tokens response."""
    return AnthropicCountTokensResponse(
        input_tokens=estimate_anthropic_input_tokens(request=request)
    )


def build_anthropic_model_list_response(
    *,
    openai_response: OpenAIModelListResponse,
) -> AnthropicModelListResponse:
    """Translate the shared live model catalog into Anthropic model objects."""
    anthropic_models = [
        AnthropicModelInfo(
            id=model.id,
            display_name=_build_anthropic_display_name(model=model),
            created_at=_format_anthropic_created_at(created=model.created),
            max_input_tokens=_build_anthropic_max_input_tokens(model=model),
            copilot=model.copilot,
        )
        for model in openai_response.data
    ]
    first_id = anthropic_models[0].id if anthropic_models else None
    last_id = anthropic_models[-1].id if anthropic_models else None
    return AnthropicModelListResponse(
        data=anthropic_models,
        first_id=first_id,
        has_more=False,
        last_id=last_id,
    )


def build_anthropic_message_response_from_text(
    *,
    model: str,
    output_text: str | None,
    message_id: str,
    usage: AnthropicUsage | None = None,
    stop_reason: str | None = 'end_turn',
) -> AnthropicMessageResponse:
    """Build a minimal Anthropic response body from assistant text."""
    content: list[AnthropicTextContentBlock] = []
    if output_text is not None:
        content.append(AnthropicTextContentBlock(text=output_text))
    return AnthropicMessageResponse(
        id=message_id,
        model=model,
        content=content,
        stop_reason=_normalize_stop_reason(stop_reason=stop_reason),
        usage=usage,
    )


def _build_anthropic_max_input_tokens(*, model: OpenAIModelCard) -> int | None:
    """Return Anthropic ``max_input_tokens`` derived from Copilot metadata.

    Args:
        model: Shared model-card entry produced by the live catalog router.

    Returns:
        The runtime-reported maximum context window for the model when available,
        otherwise ``None`` so the field is omitted from Anthropic responses.

    """
    metadata = model.copilot
    if metadata is None or metadata.capabilities is None:
        return None

    limits = metadata.capabilities.limits
    if limits is None:
        return None

    return limits.max_context_window_tokens


def build_anthropic_message_start_event(
    *,
    model: str,
    message_id: str,
    usage: AnthropicUsage | None = None,
) -> AnthropicMessageStartEvent:
    """Build the initial Anthropic streaming lifecycle event."""
    return AnthropicMessageStartEvent(
        message=AnthropicMessageResponse(
            id=message_id,
            model=model,
            content=[],
            stop_reason=None,
            usage=usage,
        )
    )


def build_anthropic_content_block_start_event() -> AnthropicContentBlockStartEvent:
    """Build the event that starts the first Anthropic text content block."""
    return AnthropicContentBlockStartEvent(
        content_block=AnthropicTextContentBlock(text='')
    )


def build_anthropic_content_block_delta_event(
    *,
    text: str,
) -> AnthropicContentBlockDeltaEvent:
    """Build one Anthropic text-delta event."""
    return AnthropicContentBlockDeltaEvent(delta=AnthropicTextDelta(text=text))


def build_anthropic_content_block_stop_event() -> AnthropicContentBlockStopEvent:
    """Build the event that closes the first Anthropic text content block."""
    return AnthropicContentBlockStopEvent()


def build_anthropic_message_delta_event(
    *,
    stop_reason: str | None = 'end_turn',
    usage: AnthropicUsage | None = None,
) -> AnthropicMessageDeltaEvent:
    """Build the top-level Anthropic message delta near stream completion."""
    return AnthropicMessageDeltaEvent(
        delta=AnthropicMessageDelta(
            stop_reason=_normalize_stop_reason(stop_reason=stop_reason)
        ),
        usage=usage,
    )


def build_anthropic_message_stop_event() -> AnthropicMessageStopEvent:
    """Build the terminal Anthropic message-stop event."""
    return AnthropicMessageStopEvent()


def build_anthropic_message_id() -> str:
    """Build a stable public identifier for one Anthropic message response."""
    return f'msg_{uuid4().hex}'


def estimate_anthropic_input_tokens(
    *,
    request: AnthropicTokenCountableRequest,
) -> int:
    """Estimate Anthropic input tokens from the serialized request payload."""
    serialized_request = json.dumps(
        _build_anthropic_token_count_payload(request=request),
        ensure_ascii=False,
        separators=(',', ':'),
        sort_keys=True,
    ).encode('utf-8')
    return max(1, math.ceil(len(serialized_request) / 4))


def estimate_anthropic_output_tokens(*, output_text: str) -> int:
    """Estimate Anthropic output tokens from assistant text using the same heuristic.

    Args:
        output_text: Assistant text emitted by the provider during one turn.

    Returns:
        A best-effort token estimate derived from UTF-8 byte length and the same
        ``/4`` heuristic used by the count-tokens compatibility helper.

    """
    return max(1, math.ceil(len(output_text.encode('utf-8')) / 4))


def build_anthropic_usage(
    *,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> AnthropicUsage | None:
    """Build an Anthropic usage payload when token accounting is available.

    Args:
        prompt_tokens: Input token count, exact or estimated.
        completion_tokens: Output token count, exact or estimated.

    Returns:
        An ``AnthropicUsage`` payload when both token counts are known; otherwise
        ``None`` so callers can omit the usage object.

    """
    if prompt_tokens is None or completion_tokens is None:
        return None

    return AnthropicUsage(
        input_tokens=prompt_tokens,
        output_tokens=completion_tokens,
    )


def _build_anthropic_token_count_payload(
    *,
    request: AnthropicTokenCountableRequest,
) -> dict[str, Any]:
    """Return the request subset that contributes to Anthropic input tokens."""
    payload: dict[str, Any] = {
        'model': request.model,
        'messages': [
            message.model_dump(exclude_none=True) for message in request.messages
        ],
    }
    if request.system is not None:
        payload['system'] = request.system
    if request.metadata is not None:
        payload['metadata'] = request.metadata
    if request.tools:
        payload['tools'] = request.tools
    return payload


def _normalize_anthropic_system_blocks(
    *,
    value: str | list[dict[str, Any]] | None,
) -> list[CanonicalChatMessage]:
    """Normalize Anthropic system blocks into canonical system messages."""
    if value is None:
        return []
    if isinstance(value, str):
        return [CanonicalChatMessage(role='system', content=value)]

    messages: list[CanonicalChatMessage] = []
    for block in value:
        block_text = _extract_text_from_content_block(block=block)
        if block_text is None:
            continue
        messages.append(CanonicalChatMessage(role='system', content=block_text))
    return messages


def _normalize_anthropic_messages(
    *,
    value: list[AnthropicMessageInput],
) -> list[CanonicalChatMessage]:
    """Normalize Anthropic input messages into canonical chat messages."""
    messages: list[CanonicalChatMessage] = []
    for message in value:
        messages.extend(
            _normalize_anthropic_message_content(
                role=message.role,
                content=message.content,
            )
        )
    return messages


def _normalize_anthropic_message_content(
    *,
    role: Literal['user', 'assistant'],
    content: str | list[dict[str, Any]],
) -> list[CanonicalChatMessage]:
    """Normalize one Anthropic message content payload."""
    if isinstance(content, str):
        return [CanonicalChatMessage(role=role, content=content)]

    messages: list[CanonicalChatMessage] = []
    for block in content:
        block_text = _extract_text_from_content_block(block=block)
        if block_text is None:
            continue
        messages.append(CanonicalChatMessage(role=role, content=block_text))
    return messages


def _extract_text_from_content_block(*, block: dict[str, Any]) -> str | None:
    """Return the text field from one Anthropic text content block when present."""
    if block.get('type') != 'text':
        return None
    text = block.get('text')
    if not isinstance(text, str) or not text:
        return None
    return text


def _normalize_stop_reason(
    *,
    stop_reason: str | None,
) -> AnthropicStopReason | None:
    """Normalize runtime stop reasons into Anthropic-compatible message reasons."""
    if stop_reason in {'length', 'max_tokens'}:
        return 'max_tokens'
    if stop_reason == 'tool_calls':
        return 'tool_use'
    if stop_reason == 'stop_sequence':
        return 'stop_sequence'
    if stop_reason == 'tool_use':
        return 'tool_use'
    if stop_reason is None:
        return None
    return 'end_turn'


def _build_anthropic_display_name(*, model: OpenAIModelCard) -> str:
    """Build a readable display name from one provider-exposed model card."""
    runtime_name = model.copilot.name if model.copilot is not None else None
    if runtime_name is not None:
        return runtime_name

    return ' '.join(
        (
            part.upper()
            if part.isalpha() and len(part) <= _DISPLAY_NAME_ACRONYM_MAX_LENGTH
            else part.capitalize()
        )
        for part in model.id.split('-')
    )


def _format_anthropic_created_at(*, created: int) -> str:
    """Format an OpenAI-style epoch timestamp for Anthropic model metadata."""
    if created <= 0:
        return '1970-01-01T00:00:00Z'
    return datetime.fromtimestamp(created, tz=UTC).isoformat().replace('+00:00', 'Z')
