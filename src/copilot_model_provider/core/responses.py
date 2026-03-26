"""Normalization and translation helpers for the OpenAI Responses surface."""

from __future__ import annotations

from time import time
from typing import TYPE_CHECKING, Literal
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
    OpenAIResponsesOutputItemAddedEvent,
    OpenAIResponsesOutputItemDoneEvent,
    OpenAIResponsesOutputMessage,
    OpenAIResponsesOutputText,
    OpenAIResponsesOutputTextDeltaEvent,
    OpenAIResponsesOutputTextDoneEvent,
    OpenAIResponsesUsage,
    RuntimeCompletion,
)

if TYPE_CHECKING:
    from copilot_model_provider.core.models import ExecutionMode


def normalize_openai_responses_request(
    *,
    request: OpenAIResponsesCreateRequest,
    request_id: str | None = None,
    conversation_id: str | None = None,
    execution_mode: ExecutionMode = 'stateless',
) -> CanonicalChatRequest:
    """Normalize an OpenAI Responses request into the provider chat contract.

    Args:
        request: The validated HTTP payload accepted by ``POST /v1/responses``.
        request_id: Optional request identifier propagated into the canonical
            execution request.
        conversation_id: Optional provider-managed conversation identifier used
            when the resolved route executes in session-backed mode.
        execution_mode: Resolved execution mode for the target public model alias.

    Returns:
        A ``CanonicalChatRequest`` suitable for routing, session preparation, and
        execution through the existing Copilot runtime path.

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
        execution_mode=execution_mode,
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
        conversation_id: Optional provider-managed conversation identifier to
            expose in the response metadata.
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
        conversation_id: Optional provider-managed conversation identifier to
            expose in the response metadata.
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
    """Build the initial streaming lifecycle event for one response stream.

    Args:
        request: The original validated Responses request body.
        response_id: Public response identifier to expose northbound.
        sequence_number: Monotonic event index for the stream.
        conversation_id: Optional provider-managed conversation identifier to
            expose in the response metadata.
        created_at: Optional Unix timestamp used for stable test assertions.

    Returns:
        A ``response.created`` event with an ``in_progress`` response envelope.

    """
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
    """Build the terminal lifecycle event for one streamed response.

    Args:
        request: The original validated Responses request body.
        response_id: Public response identifier to expose northbound.
        output_text: Fully assembled assistant text produced by the stream.
        sequence_number: Monotonic event index for the stream.
        conversation_id: Optional provider-managed conversation identifier to
            expose in the response metadata.
        created_at: Optional Unix timestamp used for stable test assertions.
        completed_at: Optional Unix timestamp used for stable test assertions.

    Returns:
        A ``response.completed`` event carrying the final response envelope.

    """
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
    """Build one ``response.output_text.delta`` event for a streamed response.

    Args:
        response_id: Public response identifier emitted by the route.
        text: Assistant text delta to expose in this event.
        sequence_number: Monotonic event index for the stream.
        output_index: Output-item index for the delta inside the response.
        content_index: Content-part index for the delta inside the output item.

    Returns:
        A streaming event compatible with the minimal Codex-needed subset.

    """
    return OpenAIResponsesOutputTextDeltaEvent(
        sequence_number=sequence_number,
        item_id=build_response_message_id(response_id=response_id),
        output_index=output_index,
        content_index=content_index,
        delta=text,
    )


def build_openai_responses_output_item_added_event(
    *,
    response_id: str,
    sequence_number: int,
    output_index: int = 0,
) -> OpenAIResponsesOutputItemAddedEvent:
    """Build the lifecycle event that opens the active output item."""
    return OpenAIResponsesOutputItemAddedEvent(
        sequence_number=sequence_number,
        output_index=output_index,
        item=OpenAIResponsesOutputMessage(
            id=build_response_message_id(response_id=response_id),
            status='in_progress',
            content=[],
        ),
    )


def build_openai_responses_content_part_added_event(
    *,
    response_id: str,
    sequence_number: int,
    output_index: int = 0,
    content_index: int = 0,
) -> OpenAIResponsesContentPartAddedEvent:
    """Build the lifecycle event that opens the active text content part."""
    return OpenAIResponsesContentPartAddedEvent(
        sequence_number=sequence_number,
        item_id=build_response_message_id(response_id=response_id),
        output_index=output_index,
        content_index=content_index,
        part=OpenAIResponsesOutputText(text=''),
    )


def build_openai_responses_output_text_done_event(
    *,
    response_id: str,
    text: str,
    sequence_number: int,
    output_index: int = 0,
    content_index: int = 0,
) -> OpenAIResponsesOutputTextDoneEvent:
    """Build the lifecycle event that finalizes one output-text part."""
    return OpenAIResponsesOutputTextDoneEvent(
        sequence_number=sequence_number,
        item_id=build_response_message_id(response_id=response_id),
        output_index=output_index,
        content_index=content_index,
        text=text,
    )


def build_openai_responses_content_part_done_event(
    *,
    response_id: str,
    text: str,
    sequence_number: int,
    output_index: int = 0,
    content_index: int = 0,
) -> OpenAIResponsesContentPartDoneEvent:
    """Build the lifecycle event that finalizes the active content part."""
    return OpenAIResponsesContentPartDoneEvent(
        sequence_number=sequence_number,
        item_id=build_response_message_id(response_id=response_id),
        output_index=output_index,
        content_index=content_index,
        part=OpenAIResponsesOutputText(text=text),
    )


def build_openai_responses_output_item_done_event(
    *,
    response_id: str,
    text: str,
    sequence_number: int,
    output_index: int = 0,
) -> OpenAIResponsesOutputItemDoneEvent:
    """Build the lifecycle event that finalizes the active output item."""
    return OpenAIResponsesOutputItemDoneEvent(
        sequence_number=sequence_number,
        output_index=output_index,
        item=build_openai_responses_output_message(
            response_id=response_id,
            output_text=text,
            status='completed',
        ),
    )


def _normalize_responses_message_block(
    *,
    value: str | list[OpenAIResponsesInputMessage],
    default_role: Literal['system', 'user'],
) -> list[CanonicalChatMessage]:
    """Normalize one Responses message block into canonical chat messages.

    Args:
        value: Either a plain string shorthand or a structured list of message
            items accepted by the Responses API.
        default_role: Role used when ``value`` is the plain-string shorthand.

    Returns:
        A list of normalized canonical chat messages that can be routed into the
        existing runtime execution path.

    """
    if isinstance(value, str):
        return [CanonicalChatMessage(role=default_role, content=value)]

    return [_normalize_responses_message(message=message) for message in value]


def build_openai_responses_output_message(
    *,
    response_id: str,
    output_text: str,
    status: Literal['in_progress', 'completed'],
) -> OpenAIResponsesOutputMessage:
    """Build one assistant output-message item for Responses payloads/events."""
    return OpenAIResponsesOutputMessage(
        id=build_response_message_id(response_id=response_id),
        status=status,
        content=[OpenAIResponsesOutputText(text=output_text)],
    )


def _normalize_responses_message(
    *,
    message: OpenAIResponsesInputMessage,
) -> CanonicalChatMessage:
    """Normalize one structured Responses message into the canonical contract.

    Args:
        message: Structured input item accepted by the Responses API route.

    Returns:
        A canonical chat message with the closest provider-supported role and a
        concatenated plain-text body.

    """
    return CanonicalChatMessage(
        role=_normalize_responses_role(role=message.role),
        content=_render_responses_message_content(message=message),
    )


def _normalize_responses_role(
    *,
    role: Literal['system', 'developer', 'user', 'assistant'],
) -> Literal['system', 'user', 'assistant']:
    """Map Responses message roles onto the provider's canonical chat roles."""
    if role in {'system', 'developer'}:
        return 'system'
    if role == 'assistant':
        return 'assistant'
    return 'user'


def _render_responses_message_content(*, message: OpenAIResponsesInputMessage) -> str:
    """Render one structured Responses message into plain assistant-visible text.

    Args:
        message: Structured input item whose content may be a plain string or a
            list of text content parts.

    Returns:
        The concatenated text content for the input message.

    """
    if isinstance(message.content, str):
        return message.content

    return ''.join(part.text for part in message.content)
