"""Unit tests for the minimal OpenAI Responses helpers."""

from __future__ import annotations

from typing import cast

from copilot_model_provider.core.models import (
    OpenAIResponsesCreateRequest,
    OpenAIResponsesFunctionCallOutputItem,
    OpenAIResponsesInputContentPart,
    OpenAIResponsesInputMessage,
    OpenAIResponsesOutputMessage,
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
                    OpenAIResponsesInputContentPart(
                        type='input_text',
                        text='Developer context',
                    )
                ],
            ),
            OpenAIResponsesInputMessage(
                role='user',
                content=[
                    OpenAIResponsesInputContentPart(
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
    )

    assert normalized.request_id == 'req-123'
    assert normalized.conversation_id == 'conversation-1'
    assert normalized.stream is True
    assert normalized.tool_routing_policy.mode == 'none'
    assert [message.model_dump() for message in normalized.messages] == [
        {'role': 'system', 'content': 'Top-level instructions'},
        {'role': 'system', 'content': 'Developer context'},
        {'role': 'user', 'content': 'User prompt'},
    ]


def test_normalize_openai_responses_request_ignores_non_text_content_parts() -> None:
    """Verify that non-text Responses content parts do not fail normalization."""
    request = OpenAIResponsesCreateRequest(
        model='default',
        input=[
            OpenAIResponsesInputMessage(
                role='user',
                content=[
                    OpenAIResponsesInputContentPart(
                        type='input_text', text='Describe this'
                    ),
                    OpenAIResponsesInputContentPart(type='input_image'),
                    OpenAIResponsesInputContentPart(type='input_file'),
                ],
            )
        ],
    )

    normalized = normalize_openai_responses_request(request=request)

    assert [message.model_dump() for message in normalized.messages] == [
        {'role': 'user', 'content': 'Describe this'}
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
        created_at=1_735_689_600,
    )

    assert response.id == 'resp_req-456'
    assert response.status == 'completed'
    assert response.model == 'default'
    output_message = cast('OpenAIResponsesOutputMessage', response.output[0])
    assert output_message.content[0].text == 'Hi from runtime.'
    assert response.usage is not None
    assert response.usage.model_dump() == {
        'input_tokens': 11,
        'output_tokens': 7,
        'total_tokens': 18,
    }
    assert response.conversation is None


def test_normalize_openai_responses_request_preserves_web_search_and_custom_tools() -> (
    None
):
    """Verify that non-function Responses tools survive canonical normalization."""
    request = OpenAIResponsesCreateRequest(
        model='default',
        input='Research this topic',
        tools=[
            {'type': 'web_search'},
            {
                'type': 'custom',
                'name': 'apply_patch',
                'description': 'Apply a patch to local files.',
            },
        ],
    )

    normalized = normalize_openai_responses_request(request=request)

    assert [tool.name for tool in normalized.tool_definitions] == [
        'web_search',
        'apply_patch',
    ]
    assert normalized.tool_definitions[0].description
    assert normalized.tool_definitions[0].parameters == {
        'type': 'object',
        'properties': {
            'query': {
                'type': 'string',
                'description': 'Search query.',
            }
        },
        'required': ['query'],
        'additionalProperties': False,
    }
    assert normalized.tool_definitions[1].description == 'Apply a patch to local files.'
    assert normalized.tool_routing_policy.mode == 'client_passthrough'
    assert normalized.tool_routing_policy.hint is not None
    assert normalized.tool_routing_policy.hint.surface == 'openai_responses'
    assert normalized.tool_routing_policy.excluded_builtin_tools == (
        'web_search',
        'web_fetch',
    )
    assert normalized.tool_routing_policy.guidance is not None


def test_normalize_openai_responses_request_preserves_routing_hints_on_continuation() -> (
    None
):
    """Verify that continuation turns preserve the shared routing-policy hints."""
    request = OpenAIResponsesCreateRequest(
        model='default',
        input=[
            OpenAIResponsesFunctionCallOutputItem(
                call_id='call_123',
                output='Done',
            )
        ],
        previous_response_id='resp_123',
        tool_choice='required',
        parallel_tool_calls=True,
    )

    normalized = normalize_openai_responses_request(
        request=request,
        session_id='provider-session-123',
    )

    assert normalized.tool_results[0].call_id == 'call_123'
    assert normalized.tool_routing_policy.mode == 'client_passthrough'
    assert normalized.tool_routing_policy.hint is not None
    assert normalized.tool_routing_policy.hint.tool_choice == 'required'
    assert normalized.tool_routing_policy.hint.parallel_tool_calls is True


def test_build_openai_responses_response_from_completion_normalizes_web_search_tools() -> (
    None
):
    """Verify that Responses payloads expose web search as a named function tool."""
    request = OpenAIResponsesCreateRequest(
        model='default',
        input='Hello',
        tools=[{'type': 'web_search'}],
    )

    response = build_openai_responses_response_from_completion(
        request=request,
        completion=RuntimeCompletion(output_text='Hi from runtime.'),
        response_id=build_response_id(request_id='req-web-search'),
    )

    assert response.tools == [
        {
            'type': 'function',
            'name': 'web_search',
            'description': 'Search the web for recent information and official sources.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'query': {
                        'type': 'string',
                        'description': 'Search query.',
                    }
                },
                'required': ['query'],
                'additionalProperties': False,
            },
        }
    ]


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
