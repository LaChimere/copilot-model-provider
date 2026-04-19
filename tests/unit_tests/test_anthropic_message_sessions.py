"""Unit tests for Anthropic message-session recovery helpers."""

from __future__ import annotations

import asyncio

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

    session_id, accepted_tool_result_ids = _pop_pending_session_id_from_tool_results(
        request=_build_tool_result_request('toolu_1'),
        pending_sessions_by_tool_use_id=pending_sessions,
        pending_tool_use_batches_by_session_id={'session_123': frozenset({'toolu_1'})},
    )

    assert session_id == 'session_123'
    assert accepted_tool_result_ids == frozenset({'toolu_1'})
    assert pending_sessions == {}


def test_pop_pending_session_id_from_tool_results_rejects_missing_session() -> None:
    """Verify that unmatched Anthropic tool results fail with the missing-session error."""
    with pytest.raises(ProviderError) as error_info:
        _pop_pending_session_id_from_tool_results(
            request=_build_tool_result_request('toolu_missing'),
            pending_sessions_by_tool_use_id={},
            pending_tool_use_batches_by_session_id={},
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
            pending_tool_use_batches_by_session_id={
                'session_123': frozenset({'toolu_1'}),
                'session_456': frozenset({'toolu_2'}),
            },
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


def test_pop_pending_session_id_from_tool_results_rejects_partial_batch() -> None:
    """Verify that Anthropic continuations must submit the full pending tool batch."""
    pending_sessions = {
        'toolu_1': 'session_123',
        'toolu_2': 'session_123',
    }

    with pytest.raises(ProviderError) as error_info:
        _pop_pending_session_id_from_tool_results(
            request=_build_tool_result_request('toolu_1'),
            pending_sessions_by_tool_use_id=pending_sessions,
            pending_tool_use_batches_by_session_id={
                'session_123': frozenset({'toolu_1', 'toolu_2'})
            },
        )

    assert error_info.value.code == 'invalid_tool_result'
    assert (
        error_info.value.message
        == 'Tool result blocks must provide the full pending tool-result batch.'
    )
    assert pending_sessions == {
        'toolu_1': 'session_123',
        'toolu_2': 'session_123',
    }


def test_pop_pending_session_id_from_tool_results_rejects_duplicate_tool_use_ids() -> (
    None
):
    """Verify that duplicate Anthropic tool_result ids are rejected explicitly."""
    pending_sessions = {'toolu_1': 'session_123'}

    with pytest.raises(ProviderError) as error_info:
        _pop_pending_session_id_from_tool_results(
            request=_build_tool_result_request('toolu_1', 'toolu_1'),
            pending_sessions_by_tool_use_id=pending_sessions,
            pending_tool_use_batches_by_session_id={
                'session_123': frozenset({'toolu_1'})
            },
        )

    assert error_info.value.code == 'invalid_tool_result'
    assert (
        error_info.value.message
        == 'Tool result blocks must not repeat the same tool_use_id.'
    )


def test_pop_pending_session_id_from_tool_results_rejects_sequential_duplicate_attempt() -> (
    None
):
    """Verify one consumed Anthropic paused turn cannot be resumed twice sequentially."""
    pending_sessions = {'toolu_1': 'session_123'}
    pending_tool_use_batches_by_session_id = {'session_123': frozenset({'toolu_1'})}

    session_id, accepted_tool_result_ids = _pop_pending_session_id_from_tool_results(
        request=_build_tool_result_request('toolu_1'),
        pending_sessions_by_tool_use_id=pending_sessions,
        pending_tool_use_batches_by_session_id=pending_tool_use_batches_by_session_id,
    )

    assert session_id == 'session_123'
    assert accepted_tool_result_ids == frozenset({'toolu_1'})

    with pytest.raises(ProviderError) as error_info:
        _pop_pending_session_id_from_tool_results(
            request=_build_tool_result_request('toolu_1'),
            pending_sessions_by_tool_use_id=pending_sessions,
            pending_tool_use_batches_by_session_id=pending_tool_use_batches_by_session_id,
        )

    assert error_info.value.code == 'invalid_tool_result'


@pytest.mark.asyncio
async def test_pop_pending_session_id_from_tool_results_allows_only_one_concurrent_duplicate_attempt() -> (
    None
):
    """Verify concurrent Anthropic duplicate attempts yield one winner and one rejection."""
    pending_sessions = {'toolu_1': 'session_123'}
    pending_tool_use_batches_by_session_id = {'session_123': frozenset({'toolu_1'})}
    release_event = asyncio.Event()

    async def _attempt_resume() -> tuple[str, str]:
        """Attempt one duplicated Anthropic continuation after both contenders are ready."""
        await release_event.wait()
        try:
            session_id, _ = _pop_pending_session_id_from_tool_results(
                request=_build_tool_result_request('toolu_1'),
                pending_sessions_by_tool_use_id=pending_sessions,
                pending_tool_use_batches_by_session_id=(
                    pending_tool_use_batches_by_session_id
                ),
            )
        except ProviderError as error:
            return 'error', error.code
        return 'ok', session_id or ''

    first_task = asyncio.create_task(_attempt_resume())
    second_task = asyncio.create_task(_attempt_resume())
    await asyncio.sleep(0)
    release_event.set()
    results = sorted(await asyncio.gather(first_task, second_task))

    assert results == [('error', 'invalid_tool_result'), ('ok', 'session_123')]
