"""Black-box integration tests for containerized Responses compatibility."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

from tests.contract_tests.helpers import parse_sse_frames

if TYPE_CHECKING:
    import httpx

_RESPONSES_TOOL_PROMPT = (
    'Before any natural-language response, call the read_file function with '
    'path README.md. After receiving the tool result, reply with exactly the '
    'tool result text and nothing else.'
)
_TOOL_RESULT_TEXT = 'INTEGRATION_TOOL_LOOP_OK'


def _build_responses_read_file_tool() -> dict[str, object]:
    """Return the OpenAI Responses tool definition used by integration tests.

    Returns:
        A JSON-serializable Responses tool descriptor for the ``read_file``
        function used to exercise the provider's tool-loop passthrough.

    """
    return {
        'type': 'function',
        'function': {
            'name': 'read_file',
            'description': 'Read one file from the workspace.',
            'parameters': {
                'type': 'object',
                'properties': {'path': {'type': 'string'}},
                'required': ['path'],
            },
        },
    }


def _extract_function_call_items(
    *, output: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return the function-call output items from one Responses payload.

    Args:
        output: OpenAI Responses ``output`` items returned by the provider.

    Returns:
        All ``function_call`` items present in the response payload.

    Raises:
        AssertionError: If the response does not contain any function-call items.

    """
    function_call_items = [
        item for item in output if item.get('type') == 'function_call'
    ]
    assert function_call_items
    return function_call_items


def _extract_message_text(*, output: list[dict[str, Any]]) -> str:
    """Return the assistant text from one Responses payload.

    Args:
        output: OpenAI Responses ``output`` items returned by the provider.

    Returns:
        The stripped text from the first assistant message item.

    Raises:
        AssertionError: If the response does not contain an assistant message
            text item.

    """
    message_item = next(item for item in output if item.get('type') == 'message')
    content = cast('list[dict[str, Any]]', message_item['content'])
    return cast('str', content[0]['text']).strip()


def _extract_completed_response(*, payload: str) -> dict[str, Any]:
    """Return the completed Responses payload from one SSE response body.

    Args:
        payload: Raw SSE response text emitted by the provider.

    Returns:
        The ``response`` object nested inside the completed SSE event.

    Raises:
        AssertionError: If the stream does not contain a completed event.

    """
    frames = parse_sse_frames(payload=payload)
    completed_frame = next(
        frame
        for frame in frames
        if '"type":"response.completed"' in frame.get('data', '')
    )
    completed_event = cast('dict[str, Any]', json.loads(completed_frame['data']))
    return cast('dict[str, Any]', completed_event['response'])


def test_container_responses_non_streaming_supports_live_model_id(
    integration_client: httpx.Client,
    integration_github_token: str,
    integration_model_id: str,
) -> None:
    """Verify that the Responses JSON surface works with one live model ID."""
    response = integration_client.post(
        '/openai/v1/responses',
        headers={'Authorization': f'Bearer {integration_github_token}'},
        json={
            'model': integration_model_id,
            'input': 'Reply with exactly RESPONSES_PING and nothing else.',
            'stream': False,
            'truncation': 'auto',
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload['object'] == 'response'
    assert payload['model'] == integration_model_id
    assert payload['output'][0]['content'][0]['text'].strip() == 'RESPONSES_PING'


def test_container_responses_streaming_emits_expected_lifecycle(
    integration_client: httpx.Client,
    integration_github_token: str,
    integration_model_id: str,
) -> None:
    """Verify that the containerized SSE stream emits the expected Responses frames."""
    with integration_client.stream(
        'POST',
        '/openai/v1/responses',
        headers={'Authorization': f'Bearer {integration_github_token}'},
        json={
            'model': integration_model_id,
            'input': 'Reply with exactly STREAM_PING and nothing else.',
            'stream': True,
        },
    ) as response:
        assert response.status_code == 200
        assert response.headers['content-type'].startswith('text/event-stream')
        payload = ''.join(response.iter_text())

    assert '"type":"response.created"' in payload
    assert '"type":"response.completed"' in payload
    assert 'STREAM_PING' in payload


def test_container_responses_streaming_tool_call_supports_continuation(
    integration_client: httpx.Client,
    integration_github_token: str,
    integration_openai_tool_model_id: str,
) -> None:
    """Verify that containerized Responses streams can pause on and resume a tool turn."""
    first_request_body: dict[str, object] = {
        'model': integration_openai_tool_model_id,
        'input': _RESPONSES_TOOL_PROMPT,
        'stream': True,
        'tools': [_build_responses_read_file_tool()],
    }
    with integration_client.stream(
        'POST',
        '/openai/v1/responses',
        headers={'Authorization': f'Bearer {integration_github_token}'},
        json=first_request_body,
    ) as response:
        assert response.status_code == 200
        assert response.headers['content-type'].startswith('text/event-stream')
        first_payload = ''.join(response.iter_text())

    completed_response = _extract_completed_response(payload=first_payload)
    response_id = cast('str', completed_response['id'])
    output = cast('list[dict[str, Any]]', completed_response['output'])
    function_call_items = _extract_function_call_items(output=output)
    read_file_call = next(
        item for item in function_call_items if item.get('name') == 'read_file'
    )

    assert '"path":"README.md"' in cast('str', read_file_call['arguments'])

    follow_up = integration_client.post(
        '/openai/v1/responses',
        headers={'Authorization': f'Bearer {integration_github_token}'},
        json={
            'model': integration_openai_tool_model_id,
            'previous_response_id': response_id,
            'input': [
                {
                    'type': 'function_call_output',
                    'call_id': cast('str', function_call_item['call_id']),
                    'output': _TOOL_RESULT_TEXT,
                }
                for function_call_item in function_call_items
            ],
        },
    )

    assert follow_up.status_code == 200
    follow_up_payload = cast('dict[str, Any]', follow_up.json())
    follow_up_output = cast('list[dict[str, Any]]', follow_up_payload['output'])
    assert _extract_message_text(output=follow_up_output) == _TOOL_RESULT_TEXT


def test_container_responses_streaming_tool_call_supports_replayed_continuation(
    integration_client: httpx.Client,
    integration_github_token: str,
    integration_openai_tool_model_id: str,
) -> None:
    """Verify that replayed function_call inputs can resume a pending Responses turn."""
    first_request_body: dict[str, object] = {
        'model': integration_openai_tool_model_id,
        'input': _RESPONSES_TOOL_PROMPT,
        'stream': True,
        'tools': [_build_responses_read_file_tool()],
    }
    with integration_client.stream(
        'POST',
        '/openai/v1/responses',
        headers={'Authorization': f'Bearer {integration_github_token}'},
        json=first_request_body,
    ) as response:
        assert response.status_code == 200
        assert response.headers['content-type'].startswith('text/event-stream')
        first_payload = ''.join(response.iter_text())

    completed_response = _extract_completed_response(payload=first_payload)
    output = cast('list[dict[str, Any]]', completed_response['output'])
    function_call_items = _extract_function_call_items(output=output)
    follow_up_request: dict[str, object] = {
        'model': integration_openai_tool_model_id,
        'input': [
            {
                'type': 'message',
                'role': 'user',
                'content': _RESPONSES_TOOL_PROMPT,
            },
            {
                'type': 'message',
                'role': 'assistant',
                'content': 'I will inspect README.md.',
                'phase': 'commentary',
            },
        ],
    }
    follow_up_input = cast('list[dict[str, object]]', follow_up_request['input'])
    follow_up_input.extend(
        [
            {
                'type': 'function_call',
                'call_id': cast('str', function_call_item['call_id']),
                'name': cast('str', function_call_item['name']),
                'arguments': cast('str', function_call_item['arguments']),
            }
            for function_call_item in function_call_items
        ]
    )
    follow_up_input.extend(
        [
            {
                'type': 'function_call_output',
                'call_id': cast('str', function_call_item['call_id']),
                'output': _TOOL_RESULT_TEXT,
            }
            for function_call_item in function_call_items
        ]
    )

    follow_up = integration_client.post(
        '/openai/v1/responses',
        headers={'Authorization': f'Bearer {integration_github_token}'},
        json=follow_up_request,
    )

    assert follow_up.status_code == 200
    follow_up_payload = cast('dict[str, Any]', follow_up.json())
    follow_up_output = cast('list[dict[str, Any]]', follow_up_payload['output'])
    assert _extract_message_text(output=follow_up_output) == _TOOL_RESULT_TEXT
