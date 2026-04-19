"""Unit tests for OpenAI Responses session-recovery helpers."""

from __future__ import annotations

import asyncio

import pytest

from copilot_model_provider.api.openai.responses import _pop_pending_session_id
from copilot_model_provider.core.errors import ProviderError
from copilot_model_provider.core.models import (
    OpenAIResponsesCreateRequest,
    OpenAIResponsesFunctionCallOutputItem,
    OpenAIResponsesInputMessage,
)
from copilot_model_provider.core.pending_turns import (
    InMemoryPendingTurnStore,
    PausedTurnRecord,
)


def _build_tool_result_request(*call_ids: str) -> OpenAIResponsesCreateRequest:
    """Build a Responses request carrying one or more ``function_call_output`` items."""
    return OpenAIResponsesCreateRequest(
        model='gpt-5.4',
        input=[
            OpenAIResponsesFunctionCallOutputItem(
                call_id=call_id,
                output=f'result for {call_id}',
            )
            for call_id in call_ids
        ],
    )


async def _build_pending_turn_state(
    *,
    response_id: str = 'resp_123',
    session_id: str = 'session_123',
    call_ids: tuple[str, ...] = ('call_1',),
) -> tuple[InMemoryPendingTurnStore, dict[str, str], dict[str, str]]:
    """Build one pending-turn store plus OpenAI-specific lookup indexes for tests."""
    store = InMemoryPendingTurnStore(time_factory=lambda: 1000.0)
    await store.remember(
        record=PausedTurnRecord(
            session_id=session_id,
            tool_ids=frozenset(call_ids),
            request_model_id='gpt-5.4',
            runtime_model_id='copilot:gpt-5.4',
            auth_context_fingerprint='token:test',
            expires_at=1005.0,
        )
    )
    return (
        store,
        {response_id: session_id},
        dict.fromkeys(call_ids, session_id),
    )


@pytest.mark.asyncio
async def test_pop_pending_session_id_returns_matching_session() -> None:
    """Verify that matched Responses tool results resolve and consume one session."""
    (
        pending_turn_store,
        pending_sessions_by_response_id,
        pending_sessions_by_tool_call_id,
    ) = await _build_pending_turn_state()

    session_id, accepted_tool_result_call_ids = await _pop_pending_session_id(
        request=_build_tool_result_request('call_1'),
        pending_turn_store=pending_turn_store,
        pending_sessions_by_response_id=pending_sessions_by_response_id,
        pending_sessions_by_tool_call_id=pending_sessions_by_tool_call_id,
        previous_response_id=None,
    )

    assert session_id == 'session_123'
    assert accepted_tool_result_call_ids == frozenset({'call_1'})
    assert pending_sessions_by_response_id == {}
    assert pending_sessions_by_tool_call_id == {}
    assert await pending_turn_store.get(session_id='session_123') is None


@pytest.mark.asyncio
async def test_pop_pending_session_id_rejects_missing_session() -> None:
    """Verify that unmatched Responses tool results fail with the missing-session error."""
    with pytest.raises(ProviderError) as error_info:
        await _pop_pending_session_id(
            request=_build_tool_result_request('call_missing'),
            pending_turn_store=InMemoryPendingTurnStore(),
            pending_sessions_by_response_id={},
            pending_sessions_by_tool_call_id={},
            previous_response_id=None,
        )

    assert error_info.value.code == 'invalid_tool_result'
    assert (
        error_info.value.message
        == 'No pending provider session matched the supplied function_call_output items.'
    )


@pytest.mark.asyncio
async def test_pop_pending_session_id_rejects_partial_batch_without_consuming_session() -> (
    None
):
    """Verify that partial Responses tool-result batches fail without clearing state."""
    (
        pending_turn_store,
        pending_sessions_by_response_id,
        pending_sessions_by_tool_call_id,
    ) = await _build_pending_turn_state(call_ids=('call_1', 'call_2'))

    with pytest.raises(ProviderError) as error_info:
        await _pop_pending_session_id(
            request=_build_tool_result_request('call_1'),
            pending_turn_store=pending_turn_store,
            pending_sessions_by_response_id=pending_sessions_by_response_id,
            pending_sessions_by_tool_call_id=pending_sessions_by_tool_call_id,
            previous_response_id='resp_123',
        )

    assert error_info.value.code == 'invalid_tool_result'
    assert (
        error_info.value.message
        == 'Function call output items must provide the full pending tool-result batch.'
    )
    assert pending_sessions_by_response_id == {'resp_123': 'session_123'}
    assert pending_sessions_by_tool_call_id == {
        'call_1': 'session_123',
        'call_2': 'session_123',
    }
    assert await pending_turn_store.get(session_id='session_123') is not None


@pytest.mark.asyncio
async def test_pop_pending_session_id_ignores_historical_replayed_tool_results() -> (
    None
):
    """Verify that replayed historical tool outputs do not break current batch recovery."""
    (
        pending_turn_store,
        pending_sessions_by_response_id,
        pending_sessions_by_tool_call_id,
    ) = await _build_pending_turn_state(
        response_id='resp_456',
        session_id='session_456',
        call_ids=('call_2', 'call_3'),
    )

    session_id, accepted_tool_result_call_ids = await _pop_pending_session_id(
        request=_build_tool_result_request('call_1', 'call_2', 'call_3'),
        pending_turn_store=pending_turn_store,
        pending_sessions_by_response_id=pending_sessions_by_response_id,
        pending_sessions_by_tool_call_id=pending_sessions_by_tool_call_id,
        previous_response_id=None,
    )

    assert session_id == 'session_456'
    assert accepted_tool_result_call_ids == frozenset({'call_2', 'call_3'})
    assert pending_sessions_by_response_id == {}
    assert pending_sessions_by_tool_call_id == {}


@pytest.mark.asyncio
async def test_pop_pending_session_id_rejects_duplicate_tool_result_call_ids() -> None:
    """Verify that duplicate function_call_output items are rejected explicitly."""
    (
        pending_turn_store,
        pending_sessions_by_response_id,
        pending_sessions_by_tool_call_id,
    ) = await _build_pending_turn_state()

    with pytest.raises(ProviderError) as error_info:
        await _pop_pending_session_id(
            request=_build_tool_result_request('call_1', 'call_1'),
            pending_turn_store=pending_turn_store,
            pending_sessions_by_response_id=pending_sessions_by_response_id,
            pending_sessions_by_tool_call_id=pending_sessions_by_tool_call_id,
            previous_response_id='resp_123',
        )

    assert error_info.value.code == 'invalid_tool_result'
    assert (
        error_info.value.message
        == 'Function call output items must not repeat the same call_id.'
    )


@pytest.mark.asyncio
async def test_pop_pending_session_id_rejects_sequential_duplicate_attempt() -> None:
    """Verify one consumed Responses paused turn cannot be resumed twice sequentially."""
    (
        pending_turn_store,
        pending_sessions_by_response_id,
        pending_sessions_by_tool_call_id,
    ) = await _build_pending_turn_state()

    session_id, accepted_tool_result_call_ids = await _pop_pending_session_id(
        request=_build_tool_result_request('call_1'),
        pending_turn_store=pending_turn_store,
        pending_sessions_by_response_id=pending_sessions_by_response_id,
        pending_sessions_by_tool_call_id=pending_sessions_by_tool_call_id,
        previous_response_id='resp_123',
    )

    assert session_id == 'session_123'
    assert accepted_tool_result_call_ids == frozenset({'call_1'})

    with pytest.raises(ProviderError) as error_info:
        await _pop_pending_session_id(
            request=_build_tool_result_request('call_1'),
            pending_turn_store=pending_turn_store,
            pending_sessions_by_response_id=pending_sessions_by_response_id,
            pending_sessions_by_tool_call_id=pending_sessions_by_tool_call_id,
            previous_response_id='resp_123',
        )

    assert error_info.value.code == 'invalid_previous_response_id'


@pytest.mark.asyncio
async def test_pop_pending_session_id_allows_only_one_concurrent_duplicate_attempt() -> (
    None
):
    """Verify concurrent Responses duplicate attempts yield one winner and one rejection."""
    (
        pending_turn_store,
        pending_sessions_by_response_id,
        pending_sessions_by_tool_call_id,
    ) = await _build_pending_turn_state()
    release_event = asyncio.Event()

    async def _attempt_resume() -> tuple[str, str]:
        """Attempt one duplicated continuation after both contenders are ready."""
        await release_event.wait()
        try:
            session_id, _ = await _pop_pending_session_id(
                request=_build_tool_result_request('call_1'),
                pending_turn_store=pending_turn_store,
                pending_sessions_by_response_id=pending_sessions_by_response_id,
                pending_sessions_by_tool_call_id=pending_sessions_by_tool_call_id,
                previous_response_id='resp_123',
            )
        except ProviderError as error:
            return 'error', error.code
        return 'ok', session_id or ''

    first_task = asyncio.create_task(_attempt_resume())
    second_task = asyncio.create_task(_attempt_resume())
    await asyncio.sleep(0)
    release_event.set()
    results = sorted(await asyncio.gather(first_task, second_task))

    assert results == [('error', 'invalid_previous_response_id'), ('ok', 'session_123')]


@pytest.mark.asyncio
async def test_pop_pending_session_id_ignores_completed_historical_tool_outputs() -> (
    None
):
    """Verify that a fresh user turn can replay completed historical tool outputs safely."""
    session_id, accepted_tool_result_call_ids = await _pop_pending_session_id(
        request=OpenAIResponsesCreateRequest(
            model='gpt-5.4',
            input=[
                OpenAIResponsesInputMessage(
                    role='user',
                    content='Old question',
                ),
                OpenAIResponsesFunctionCallOutputItem(
                    call_id='call_1',
                    output='old result',
                ),
                OpenAIResponsesInputMessage(
                    role='user',
                    content='New question',
                ),
            ],
        ),
        pending_turn_store=InMemoryPendingTurnStore(),
        pending_sessions_by_response_id={},
        pending_sessions_by_tool_call_id={},
        previous_response_id=None,
    )

    assert session_id is None
    assert accepted_tool_result_call_ids == frozenset()
