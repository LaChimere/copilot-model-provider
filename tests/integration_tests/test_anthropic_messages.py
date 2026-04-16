"""Black-box integration tests for containerized Anthropic Messages compatibility."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    import httpx

_ANTHROPIC_TOOL_PROMPT = (
    'Before any natural-language response, use the read_file tool with path '
    'README.md. After receiving the tool result, reply with exactly the tool '
    'result text and nothing else.'
)
_TOOL_RESULT_TEXT = 'INTEGRATION_TOOL_LOOP_OK'


def _build_anthropic_read_file_tool() -> dict[str, object]:
    """Return the Anthropic Messages tool definition used by integration tests.

    Returns:
        A JSON-serializable Anthropic tool descriptor for the ``read_file`` tool
        used to exercise the provider's tool-loop passthrough.

    """
    return {
        'name': 'read_file',
        'description': 'Read one file from the workspace.',
        'input_schema': {
            'type': 'object',
            'properties': {'path': {'type': 'string'}},
            'required': ['path'],
        },
    }


def _extract_tool_use_block(*, content: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the ``tool_use`` block from one Anthropic message payload.

    Args:
        content: Anthropic message ``content`` blocks returned by the provider.

    Returns:
        The first ``tool_use`` block present in the response payload.

    Raises:
        StopIteration: If the response does not contain a ``tool_use`` block.

    """
    return next(block for block in content if block.get('type') == 'tool_use')


def _extract_text_block_text(*, content: list[dict[str, Any]]) -> str:
    """Return the assistant text from one Anthropic message payload.

    Args:
        content: Anthropic message ``content`` blocks returned by the provider.

    Returns:
        The stripped text from the first ``text`` content block.

    Raises:
        StopIteration: If the response does not contain a text content block.

    """
    text_block = next(block for block in content if block.get('type') == 'text')
    return cast('str', text_block['text']).strip()


def test_container_anthropic_messages_support_tool_result_continuation(
    integration_client: httpx.Client,
    integration_github_token: str,
    integration_anthropic_model_id: str,
) -> None:
    """Verify that containerized Anthropic Messages can continue after a tool turn."""
    auth_headers = {'Authorization': f'Bearer {integration_github_token}'}
    first_request_body: dict[str, object] = {
        'model': integration_anthropic_model_id,
        'max_tokens': 256,
        'messages': [{'role': 'user', 'content': _ANTHROPIC_TOOL_PROMPT}],
        'tools': [_build_anthropic_read_file_tool()],
    }
    first_response = integration_client.post(
        '/anthropic/v1/messages',
        headers=auth_headers,
        json=first_request_body,
    )

    assert first_response.status_code == 200
    first_payload = cast('dict[str, Any]', first_response.json())
    first_content = cast('list[dict[str, Any]]', first_payload['content'])
    tool_use_block = _extract_tool_use_block(content=first_content)
    tool_use_id = cast('str', tool_use_block['id'])
    assert first_payload['stop_reason'] == 'tool_use'
    assert tool_use_block['name'] == 'read_file'
    assert cast('dict[str, Any]', tool_use_block['input'])['path'] == 'README.md'

    follow_up_request_body: dict[str, object] = {
        'model': integration_anthropic_model_id,
        'max_tokens': 256,
        'messages': [
            {
                'role': 'user',
                'content': [
                    {
                        'type': 'tool_result',
                        'tool_use_id': tool_use_id,
                        'content': _TOOL_RESULT_TEXT,
                    }
                ],
            }
        ],
    }
    follow_up = integration_client.post(
        '/anthropic/v1/messages',
        headers=auth_headers,
        json=follow_up_request_body,
    )

    assert follow_up.status_code == 200
    follow_up_payload = cast('dict[str, Any]', follow_up.json())
    follow_up_content = cast('list[dict[str, Any]]', follow_up_payload['content'])
    assert _extract_text_block_text(content=follow_up_content) == _TOOL_RESULT_TEXT
