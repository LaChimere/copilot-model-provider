"""Normalization and translation helpers for the OpenAI Responses surface."""

from __future__ import annotations

from time import time
from typing import Literal, cast
from uuid import uuid4

from copilot_model_provider.core.models import (
    CanonicalChatMessage,
    CanonicalChatRequest,
    OpenAIResponse,
    OpenAIResponsesCompletedEvent,
    OpenAIResponsesContentPartAddedEvent,
    OpenAIResponsesContentPartDoneEvent,
    OpenAIResponsesConversation,
    OpenAIResponsesCreatedEvent,
    OpenAIResponsesCreateRequest,
    OpenAIResponsesInputMessage,
    OpenAIResponsesInputTextPart,
    OpenAIResponsesOutputItemAddedEvent,
    OpenAIResponsesOutputItemDoneEvent,
    OpenAIResponsesOutputMessage,
    OpenAIResponsesOutputText,
    OpenAIResponsesOutputTextDeltaEvent,
    OpenAIResponsesOutputTextDoneEvent,
    OpenAIResponsesUsage,
    RuntimeCompletion,
)


def normalize_openai_responses_request(
    *,
    request: OpenAIResponsesCreateRequest,
    request_id: str | None = None,
    conversation_id: str | None = None,
) -> CanonicalChatRequest:
    """Normalize an OpenAI Responses request into the provider chat contract.

    Args:
        request: The validated HTTP payload accepted by ``POST /v1/responses``.
        request_id: Optional request identifier propagated into the canonical
            execution request.
        conversation_id: Optional client-supplied conversation identifier kept as
            request metadata without enabling provider-side session state.

    Returns:
        A ``CanonicalChatRequest`` suitable for routing and execution through the
        existing Copilot runtime path.

    """
    messages: list[CanonicalChatMessage] = []
    if request.instructions is not None:
        messages.extend(
            _normalize_responses_message_block(
                value=request.instructions,
                default_role='system',
            )
        )
    messages.extend(
        _normalize_responses_message_block(value=request.input, default_role='user')
    )
    return CanonicalChatRequest(
        request_id=request_id,
        conversation_id=conversation_id,
        model_alias=request.model,
        messages=messages,
        stream=request.stream,
    )


def build_response_id(*, request_id: str | None = None) -> str:
    """Build a stable Responses-style identifier for one provider request.

    Args:
        request_id: Optional upstream request identifier that should seed the
            public response identifier.

    Returns:
        A string prefixed with ``resp_`` suitable for the public Responses API.

    """
    resolved_request_id = request_id or uuid4().hex
    return (
        resolved_request_id
        if resolved_request_id.startswith('resp_')
        else f'resp_{resolved_request_id}'
    )


def build_response_message_id(*, response_id: str) -> str:
    """Build the assistant-message identifier for one Responses payload.

    Args:
        response_id: Public response identifier emitted by the route.

    Returns:
        A message identifier prefixed with ``msg_`` that stays stable across the
        stream lifecycle for the same response.

    """
    suffix = response_id.removeprefix('resp_')
    return f'msg_{suffix}'


def build_openai_responses_response_from_completion(
    *,
    request: OpenAIResponsesCreateRequest,
    completion: RuntimeCompletion,
    response_id: str,
    conversation_id: str | None = None,
    created_at: int | None = None,
) -> OpenAIResponse:
    """Translate a runtime completion into the public Responses payload.

    Args:
        request: The original validated Responses request body.
        completion: Normalized runtime output returned by the adapter.
        response_id: Public response identifier to expose northbound.
        conversation_id: Optional client-supplied conversation identifier to
            expose in response metadata.
        created_at: Optional Unix timestamp used for stable test assertions.

    Returns:
        An ``OpenAIResponse`` compatible with the minimal Codex-needed subset.

    """
    usage = None
    if (
        completion.prompt_tokens is not None
        and completion.completion_tokens is not None
    ):
        usage = OpenAIResponsesUsage(
            input_tokens=completion.prompt_tokens,
            output_tokens=completion.completion_tokens,
            total_tokens=completion.prompt_tokens + completion.completion_tokens,
        )

    return build_openai_responses_response_from_text(
        request=request,
        output_text=completion.output_text,
        response_id=response_id,
        conversation_id=conversation_id,
        created_at=created_at,
        usage=usage,
    )


def build_openai_responses_response_from_text(
    *,
    request: OpenAIResponsesCreateRequest,
    output_text: str | None,
    response_id: str,
    conversation_id: str | None = None,
    created_at: int | None = None,
    completed_at: int | None = None,
    status: Literal['completed', 'in_progress'] = 'completed',
    usage: OpenAIResponsesUsage | None = None,
) -> OpenAIResponse:
    """Build a Responses payload from pre-rendered assistant text.

    Args:
        request: The original validated Responses request body.
        output_text: Assistant text that should populate the completed output
            message. ``None`` keeps the ``output`` array empty.
        response_id: Public response identifier to expose northbound.
        conversation_id: Optional client-supplied conversation identifier to
            expose in response metadata.
        created_at: Optional Unix timestamp used for stable test assertions.
        completed_at: Optional Unix timestamp set when the response has reached
            terminal completion.
        status: Lifecycle status that should be reflected in the response body.
        usage: Optional token-usage payload when runtime accounting is available.

    Returns:
        An ``OpenAIResponse`` payload that preserves the original request shape
        while surfacing the provider-rendered assistant text.

    """
    normalized_created_at = created_at or int(time())
    normalized_completed_at = completed_at or (
        normalized_created_at if status == 'completed' else None
    )
    output: list[OpenAIResponsesOutputMessage] = []
    if output_text is not None:
        output.append(
            build_openai_responses_output_message(
                response_id=response_id,
                output_text=output_text,
                status='completed' if status == 'completed' else 'in_progress',
            )
        )

    return OpenAIResponse(
        id=response_id,
        created_at=normalized_created_at,
        completed_at=normalized_completed_at,
        status=status,
        model=request.model,
        instructions=request.instructions,
        output=output,
        parallel_tool_calls=request.parallel_tool_calls,
        tool_choice=request.tool_choice,
        tools=request.tools,
        store=request.store,
        usage=usage,
        previous_response_id=request.previous_response_id,
        conversation=(
            OpenAIResponsesConversation(id=conversation_id)
            if conversation_id is not None
            else None
        ),
    )


def build_openai_responses_created_event(
    *,
    request: OpenAIResponsesCreateRequest,
    response_id: str,
    sequence_number: int,
    conversation_id: str | None = None,
    created_at: int | None = None,
) -> OpenAIResponsesCreatedEvent:
    """Build the initial streaming lifecycle event for one response stream."""
    return OpenAIResponsesCreatedEvent(
        sequence_number=sequence_number,
        response=build_openai_responses_response_from_text(
            request=request,
            output_text=None,
            response_id=response_id,
            conversation_id=conversation_id,
            created_at=created_at,
            status='in_progress',
        ),
    )


def build_openai_responses_completed_event(
    *,
    request: OpenAIResponsesCreateRequest,
    response_id: str,
    output_text: str | None,
    sequence_number: int,
    conversation_id: str | None = None,
    created_at: int | None = None,
    completed_at: int | None = None,
) -> OpenAIResponsesCompletedEvent:
    """Build the terminal lifecycle event for one streamed response."""
    return OpenAIResponsesCompletedEvent(
        sequence_number=sequence_number,
        response=build_openai_responses_response_from_text(
            request=request,
            output_text=output_text,
            response_id=response_id,
            conversation_id=conversation_id,
            created_at=created_at,
            completed_at=completed_at,
            status='completed',
        ),
    )


def build_openai_responses_output_text_delta_event(
    *,
    response_id: str,
    text: str,
    sequence_number: int,
    output_index: int = 0,
    content_index: int = 0,
) -> OpenAIResponsesOutputTextDeltaEvent:
    """Build one ``response.output_text.delta`` event for a streamed response."""
    return OpenAIResponsesOutputTextDeltaEvent(
        sequence_number=sequence_number,
        item_id=build_response_message_id(response_id=response_id),
        output_index=output_index,
        content_index=content_index,
        delta=text,
    )


def build_openai_responses_output_text_done_event(
    *,
    response_id: str,
    text: str,
    sequence_number: int,
    output_index: int = 0,
    content_index: int = 0,
) -> OpenAIResponsesOutputTextDoneEvent:
    """Build one ``response.output_text.done`` event for a streamed response."""
    return OpenAIResponsesOutputTextDoneEvent(
        sequence_number=sequence_number,
        item_id=build_response_message_id(response_id=response_id),
        output_index=output_index,
        content_index=content_index,
        text=text,
    )


def build_openai_responses_content_part_added_event(
    *,
    response_id: str,
    sequence_number: int,
    output_index: int = 0,
    content_index: int = 0,
) -> OpenAIResponsesContentPartAddedEvent:
    """Build one ``response.content_part.added`` event for a response stream."""
    return OpenAIResponsesContentPartAddedEvent(
        sequence_number=sequence_number,
        item_id=build_response_message_id(response_id=response_id),
        output_index=output_index,
        content_index=content_index,
        part=OpenAIResponsesOutputText(text=''),
    )


def build_openai_responses_content_part_done_event(
    *,
    response_id: str,
    text: str,
    sequence_number: int,
    output_index: int = 0,
    content_index: int = 0,
) -> OpenAIResponsesContentPartDoneEvent:
    """Build one ``response.content_part.done`` event for a response stream."""
    return OpenAIResponsesContentPartDoneEvent(
        sequence_number=sequence_number,
        item_id=build_response_message_id(response_id=response_id),
        output_index=output_index,
        content_index=content_index,
        part=OpenAIResponsesOutputText(text=text),
    )


def build_openai_responses_output_item_added_event(
    *,
    response_id: str,
    sequence_number: int,
    output_index: int = 0,
) -> OpenAIResponsesOutputItemAddedEvent:
    """Build one ``response.output_item.added`` event for a response stream."""
    return OpenAIResponsesOutputItemAddedEvent(
        sequence_number=sequence_number,
        output_index=output_index,
        item=build_openai_responses_output_message(
            response_id=response_id,
            output_text='',
            status='in_progress',
        ),
    )


def build_openai_responses_output_item_done_event(
    *,
    response_id: str,
    text: str,
    sequence_number: int,
    output_index: int = 0,
) -> OpenAIResponsesOutputItemDoneEvent:
    """Build one ``response.output_item.done`` event for a response stream."""
    return OpenAIResponsesOutputItemDoneEvent(
        sequence_number=sequence_number,
        output_index=output_index,
        item=build_openai_responses_output_message(
            response_id=response_id,
            output_text=text,
            status='completed',
        ),
    )


def build_openai_responses_output_message(
    *,
    response_id: str,
    output_text: str,
    status: Literal['in_progress', 'completed'],
) -> OpenAIResponsesOutputMessage:
    """Build a single assistant output item for a Responses payload."""
    return OpenAIResponsesOutputMessage(
        id=build_response_message_id(response_id=response_id),
        status=status,
        content=[OpenAIResponsesOutputText(text=output_text)],
    )


def _normalize_responses_message_block(
    *,
    value: str | list[OpenAIResponsesInputMessage],
    default_role: Literal['system', 'user'],
) -> list[CanonicalChatMessage]:
    """Normalize a Responses message block into canonical chat messages."""
    if isinstance(value, str):
        return [CanonicalChatMessage(role=default_role, content=value)]

    normalized_messages: list[CanonicalChatMessage] = []
    for item in value:
        if item.type != 'message':
            continue

        normalized_role = (
            'system' if item.role in {'system', 'developer'} else item.role
        )
        normalized_messages.extend(
            _normalize_responses_message_content(
                role=cast("Literal['system', 'user', 'assistant']", normalized_role),
                content=item.content,
            )
        )

    return normalized_messages


def _normalize_responses_message_content(
    *,
    role: Literal['system', 'user', 'assistant'],
    content: str | list[OpenAIResponsesInputTextPart],
) -> list[CanonicalChatMessage]:
    """Normalize one Responses message content payload."""
    if isinstance(content, str):
        return [CanonicalChatMessage(role=role, content=content)]

    return [CanonicalChatMessage(role=role, content=part.text) for part in content]
