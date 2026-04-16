"""Unit tests for chat normalization and public response translation."""

from __future__ import annotations

from copilot_model_provider.core.chat import (
    build_openai_chat_completion_response,
    normalize_openai_chat_request,
    render_prompt,
)
from copilot_model_provider.core.models import (
    OpenAIChatCompletionRequest,
    OpenAIChatMessage,
    RuntimeCompletion,
)


def test_normalize_openai_chat_request_preserves_stream_and_request_metadata() -> None:
    """Verify that normalization retains request metadata for execution."""
    canonical_request = normalize_openai_chat_request(
        request=OpenAIChatCompletionRequest(
            model='default',
            stream=True,
            messages=[OpenAIChatMessage(role='user', content='Hello')],
        ),
        request_id='request-1',
        conversation_id='conversation-1',
    )

    assert canonical_request.request_id == 'request-1'
    assert canonical_request.conversation_id == 'conversation-1'
    assert canonical_request.stream is True
    assert canonical_request.messages[0].content == 'Hello'
    assert canonical_request.tool_routing_policy.mode == 'none'
    assert canonical_request.tool_routing_policy.hint is None


def test_render_prompt_preserves_roles_and_appends_assistant_turn() -> None:
    """Verify that prompt rendering keeps role boundaries explicit for Copilot."""
    canonical_request = normalize_openai_chat_request(
        request=OpenAIChatCompletionRequest(
            model='default',
            messages=[
                OpenAIChatMessage(role='system', content='Be concise.'),
                OpenAIChatMessage(role='user', content='Say hi'),
            ],
        )
    )

    assert render_prompt(request=canonical_request) == (
        'System: Be concise.\n\nUser: Say hi\n\nAssistant:'
    )


def test_build_openai_chat_completion_response_includes_usage_when_available() -> None:
    """Verify that runtime token counts are translated into OpenAI usage fields."""
    request = OpenAIChatCompletionRequest(
        model='default',
        messages=[OpenAIChatMessage(role='user', content='Hello')],
    )

    response = build_openai_chat_completion_response(
        request=request,
        completion=RuntimeCompletion(
            output_text='Hi there!',
            provider_response_id='chatcmpl-test',
            prompt_tokens=11,
            completion_tokens=7,
        ),
    )

    assert response.id == 'chatcmpl-test'
    assert response.model == 'default'
    assert response.choices[0].message.role == 'assistant'
    assert response.choices[0].message.content == 'Hi there!'
    assert response.usage is not None
    assert response.usage.total_tokens == 18
