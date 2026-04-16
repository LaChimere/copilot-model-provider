"""Unit tests for Anthropic message-session recovery helpers."""

from __future__ import annotations

import pytest

from copilot_model_provider.api.anthropic.messages import (
    _pop_pending_session_id_from_tool_results,
)
from copilot_model_provider.core.errors import ProviderError
from copilot_model_provider.core.models import (
    AnthropicMessageInput,
    AnthropicMessagesCreateRequest,
)


def _build_tool_result_request(*tool_use_ids: str) -> AnthropicMessagesCreateRequest:
    """Build an Anthropic request carrying one or more ``tool_result`` blocks."""
    return AnthropicMessagesCreateRequest(
        model='claude-sonnet-4-20250514',
        messages=[
            AnthropicMessageInput(
                role='user',
                content=[
                    {
                        'type': 'tool_result',
                        'tool_use_id': tool_use_id,
                        'content': f'result for {tool_use_id}',
                    }
                    for tool_use_id in tool_use_ids
                ],
            )
        ],
    )


def test_pop_pending_session_id_from_tool_results_returns_matching_session() -> None:
    """Verify that matched Anthropic tool results resolve and consume one session."""
    pending_sessions = {'toolu_1': 'session_123'}

    session_id = _pop_pending_session_id_from_tool_results(
        request=_build_tool_result_request('toolu_1'),
        pending_sessions_by_tool_use_id=pending_sessions,
    )

    assert session_id == 'session_123'
    assert pending_sessions == {}


def test_pop_pending_session_id_from_tool_results_rejects_missing_session() -> None:
    """Verify that unmatched Anthropic tool results fail with the missing-session error."""
    with pytest.raises(ProviderError) as error_info:
        _pop_pending_session_id_from_tool_results(
            request=_build_tool_result_request('toolu_missing'),
            pending_sessions_by_tool_use_id={},
        )

    assert error_info.value.code == 'invalid_tool_result'
    assert (
        error_info.value.message
        == 'No pending provider session matched the supplied tool_result blocks.'
    )


def test_pop_pending_session_id_from_tool_results_rejects_mismatched_sessions() -> None:
    """Verify that Anthropic tool results cannot span multiple provider sessions."""
    pending_sessions = {
        'toolu_1': 'session_123',
        'toolu_2': 'session_456',
    }

    with pytest.raises(ProviderError) as error_info:
        _pop_pending_session_id_from_tool_results(
            request=_build_tool_result_request('toolu_1', 'toolu_2'),
            pending_sessions_by_tool_use_id=pending_sessions,
        )

    assert error_info.value.code == 'invalid_tool_result'
    assert (
        error_info.value.message
        == 'Tool result blocks referenced multiple pending provider sessions.'
    )
    assert pending_sessions == {
        'toolu_1': 'session_123',
        'toolu_2': 'session_456',
    }
