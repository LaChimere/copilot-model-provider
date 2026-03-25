"""Normalization and translation helpers for the OpenAI chat surface."""

from __future__ import annotations

from time import time
from typing import TYPE_CHECKING
from uuid import uuid4

from copilot_model_provider.core.models import (
    CanonicalChatMessage,
    CanonicalChatRequest,
    OpenAIChatCompletionChoice,
    OpenAIChatCompletionRequest,
    OpenAIChatCompletionResponse,
    OpenAIChatMessage,
    OpenAIUsage,
    RuntimeCompletion,
)

if TYPE_CHECKING:
    from copilot_model_provider.core.models import ExecutionMode


def normalize_openai_chat_request(
    *,
    request: OpenAIChatCompletionRequest,
    request_id: str | None = None,
    conversation_id: str | None = None,
    execution_mode: ExecutionMode = 'stateless',
) -> CanonicalChatRequest:
    """Normalize an OpenAI-compatible chat request into the provider contract.

    Args:
        request: The validated HTTP request payload accepted by the compatibility
            route.
        request_id: Optional request identifier propagated into the canonical
            execution request.
        conversation_id: Optional provider-managed conversation identifier used
            when sessional execution is enabled for the resolved route.
        execution_mode: Resolved execution mode for the target route.

    Returns:
        A ``CanonicalChatRequest`` suitable for runtime routing and execution.

    """
    return CanonicalChatRequest(
        request_id=request_id,
        conversation_id=conversation_id,
        model_alias=request.model,
        execution_mode=execution_mode,
        messages=[
            CanonicalChatMessage(role=message.role, content=message.content)
            for message in request.messages
        ],
        stream=request.stream,
    )


def render_prompt(*, request: CanonicalChatRequest) -> str:
    """Render a canonical chat request into a prompt for the Copilot runtime.

    Args:
        request: The normalized stateless chat request.

    Returns:
        A plain-text prompt that preserves role boundaries while making the next
        expected assistant turn explicit.

    """
    labels = {
        'system': 'System',
        'user': 'User',
        'assistant': 'Assistant',
    }
    rendered_messages = [
        f'{labels[message.role]}: {message.content.strip()}'
        for message in request.messages
    ]
    rendered_messages.append('Assistant:')
    return '\n\n'.join(rendered_messages)


def build_openai_chat_completion_response(
    *,
    request: OpenAIChatCompletionRequest,
    completion: RuntimeCompletion,
) -> OpenAIChatCompletionResponse:
    """Translate a runtime completion into the public OpenAI response shape.

    Args:
        request: The original validated OpenAI-compatible HTTP request.
        completion: The normalized runtime output produced by an adapter.

    Returns:
        An ``OpenAIChatCompletionResponse`` matching the non-streaming OpenAI
        compatibility surface implemented by this slice.

    """
    usage = None
    if (
        completion.prompt_tokens is not None
        and completion.completion_tokens is not None
    ):
        usage = OpenAIUsage(
            prompt_tokens=completion.prompt_tokens,
            completion_tokens=completion.completion_tokens,
            total_tokens=completion.prompt_tokens + completion.completion_tokens,
        )

    return OpenAIChatCompletionResponse(
        id=completion.provider_response_id or f'chatcmpl-{uuid4().hex}',
        created=int(time()),
        model=request.model,
        choices=[
            OpenAIChatCompletionChoice(
                index=0,
                message=OpenAIChatMessage(
                    role='assistant',
                    content=completion.output_text,
                ),
                finish_reason=completion.finish_reason,
            )
        ],
        usage=usage,
    )
