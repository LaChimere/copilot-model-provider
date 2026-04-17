"""Unit tests for Anthropic request normalization."""

from __future__ import annotations

from copilot_model_provider.api.anthropic.protocol import (
    normalize_anthropic_messages_request,
)
from copilot_model_provider.core.models import (
    AnthropicMessageInput,
    AnthropicMessagesCreateRequest,
)


def test_normalize_anthropic_messages_request_derives_client_passthrough_policy() -> (
    None
):
    """Verify that Anthropic tool-aware requests derive the shared routing policy."""
    normalized = normalize_anthropic_messages_request(
        request=AnthropicMessagesCreateRequest(
            model='claude-sonnet-4-20250514',
            messages=[AnthropicMessageInput(role='user', content='Read README.md')],
            tools=[
                {
                    'name': 'read_file',
                    'description': 'Read a file.',
                    'input_schema': {
                        'type': 'object',
                        'properties': {'path': {'type': 'string'}},
                    },
                }
            ],
        )
    )

    assert normalized.tool_routing_policy.mode == 'client_passthrough'
    assert normalized.tool_routing_policy.hint is None
    assert normalized.tool_routing_policy.excluded_builtin_tools == (
        'web_search',
        'web_fetch',
    )


def test_normalize_anthropic_messages_request_keeps_text_only_requests_stateless() -> (
    None
):
    """Verify that Anthropic text-only requests derive the no-op routing policy."""
    normalized = normalize_anthropic_messages_request(
        request=AnthropicMessagesCreateRequest(
            model='claude-sonnet-4-20250514',
            messages=[AnthropicMessageInput(role='user', content='Hello')],
        )
    )

    assert normalized.tool_routing_policy.mode == 'none'
    assert normalized.tool_routing_policy.guidance is None


def test_normalize_anthropic_messages_request_filters_historical_tool_results() -> None:
    """Verify that Anthropic normalization keeps only the accepted tool-result batch."""
    normalized = normalize_anthropic_messages_request(
        request=AnthropicMessagesCreateRequest(
            model='claude-sonnet-4-20250514',
            messages=[
                AnthropicMessageInput(
                    role='user',
                    content=[
                        {
                            'type': 'tool_result',
                            'tool_use_id': 'toolu_old',
                            'content': 'old result',
                        },
                        {
                            'type': 'tool_result',
                            'tool_use_id': 'toolu_current',
                            'content': 'current result',
                        },
                    ],
                )
            ],
        ),
        accepted_tool_result_ids={'toolu_current'},
    )

    assert [result.model_dump() for result in normalized.tool_results] == [
        {
            'call_id': 'toolu_current',
            'output_text': 'current result',
            'is_error': False,
            'error_text': None,
        }
    ]
