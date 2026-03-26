"""Unit tests for the minimal OpenAI Responses helpers."""

from __future__ import annotations

from copilot_model_provider.core.models import (
    OpenAIResponsesCreateRequest,
    OpenAIResponsesInputMessage,
    OpenAIResponsesInputTextPart,
    RuntimeCompletion,
)
from copilot_model_provider.core.responses import (
    build_openai_responses_response_from_completion,
    build_openai_responses_response_from_text,
    build_response_id,
    normalize_openai_responses_request,
)


def test_normalize_openai_responses_request_maps_instructions_and_developer_messages() -> (
    None
):
    """Verify that Responses inputs converge onto the canonical chat contract."""
    request = OpenAIResponsesCreateRequest(
        model='default',
        instructions='Top-level instructions',
        input=[
            OpenAIResponsesInputMessage(
                role='developer',
                content=[
                    OpenAIResponsesInputTextPart(
                        type='input_text',
                        text='Developer context',
                    )
                ],
            ),
            OpenAIResponsesInputMessage(
                role='user',
                content=[
                    OpenAIResponsesInputTextPart(
                        type='input_text',
                        text='User prompt',
                    )
                ],
            ),
        ],
        stream=True,
    )

    normalized = normalize_openai_responses_request(
        request=request,
        request_id='req-123',
        conversation_id='conversation-1',
        execution_mode='sessional',
    )

    assert normalized.request_id == 'req-123'
    assert normalized.conversation_id == 'conversation-1'
    assert normalized.execution_mode == 'sessional'
    assert normalized.stream is True
    assert [message.model_dump() for message in normalized.messages] == [
        {'role': 'system', 'content': 'Top-level instructions'},
        {'role': 'system', 'content': 'Developer context'},
        {'role': 'user', 'content': 'User prompt'},
    ]


def test_build_openai_responses_response_from_completion_maps_usage() -> None:
    """Verify that runtime usage is translated into the Responses payload."""
    request = OpenAIResponsesCreateRequest(model='default', input='Hello')
    response = build_openai_responses_response_from_completion(
        request=request,
        completion=RuntimeCompletion(
            output_text='Hi from runtime.',
            prompt_tokens=11,
            completion_tokens=7,
        ),
        response_id=build_response_id(request_id='req-456'),
        conversation_id='conversation-2',
        created_at=1_735_689_600,
    )

    assert response.id == 'resp_req-456'
    assert response.status == 'completed'
    assert response.model == 'default'
    assert response.output[0].content[0].text == 'Hi from runtime.'
    assert response.usage is not None
    assert response.usage.model_dump() == {
        'input_tokens': 11,
        'output_tokens': 7,
        'total_tokens': 18,
    }
    assert response.conversation is not None
    assert response.conversation.model_dump() == {'id': 'conversation-2'}


def test_build_openai_responses_response_from_text_can_render_in_progress_payload() -> (
    None
):
    """Verify that stream lifecycle helpers can render in-progress envelopes."""
    request = OpenAIResponsesCreateRequest(model='default', input='Ping')
    response = build_openai_responses_response_from_text(
        request=request,
        output_text=None,
        response_id='resp_req-789',
        status='in_progress',
        created_at=1_735_689_600,
    )

    assert response.id == 'resp_req-789'
    assert response.status == 'in_progress'
    assert response.output == []
    assert response.completed_at is None
