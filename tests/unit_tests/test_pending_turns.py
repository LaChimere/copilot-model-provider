"""Unit tests for the shared paused-turn store."""

from __future__ import annotations

import asyncio

import pytest

from copilot_model_provider.core.pending_turns import (
    InMemoryPendingTurnStore,
    PausedTurnRecord,
    build_auth_context_fingerprint,
    build_paused_turn_record,
)
from copilot_model_provider.core.routing import DEFAULT_AUTH_CONTEXT_CACHE_KEY


def test_build_auth_context_fingerprint_matches_shared_cache_key_format() -> None:
    """Verify paused-turn auth fingerprints reuse the shared auth-context key shape."""
    assert (
        build_auth_context_fingerprint(runtime_auth_token=None)
        == DEFAULT_AUTH_CONTEXT_CACHE_KEY
    )

    fingerprint = build_auth_context_fingerprint(
        runtime_auth_token='ghu_test_token',  # noqa: S106
    )

    assert fingerprint.startswith('token:')
    assert fingerprint != 'token:ghu_test_token'


def test_build_paused_turn_record_captures_required_base_slice_fields() -> None:
    """Verify paused-turn records preserve the required continuation-affinity data."""
    record = build_paused_turn_record(
        session_id='session_123',
        tool_ids=('call_1', 'call_2'),
        request_model_id='gpt-5.4',
        runtime_model_id='copilot:gpt-5.4',
        runtime_auth_token='ghu_test_token',  # noqa: S106
        expires_at=1234.5,
    )

    assert record.session_id == 'session_123'
    assert record.tool_ids == frozenset({'call_1', 'call_2'})
    assert record.request_model_id == 'gpt-5.4'
    assert record.runtime_model_id == 'copilot:gpt-5.4'
    assert record.auth_context_fingerprint.startswith('token:')
    assert record.expires_at == 1234.5


@pytest.mark.asyncio
async def test_pending_turn_store_resolves_and_consumes_matching_full_batch() -> None:
    """Verify the store resolves one full tool-result batch exactly once."""
    store = InMemoryPendingTurnStore(time_factory=lambda: 1000.0)
    await store.remember(
        record=PausedTurnRecord(
            session_id='session_123',
            tool_ids=frozenset({'call_1', 'call_2'}),
            request_model_id='gpt-5.4',
            runtime_model_id='copilot:gpt-5.4',
            auth_context_fingerprint='token:test',
            expires_at=1005.0,
        )
    )

    resolution = await store.resolve(tool_ids=('call_1', 'call_2'))
    second_resolution = await store.resolve(tool_ids=('call_1', 'call_2'))

    assert resolution.status == 'ready_to_resume'
    assert resolution.record is not None
    assert resolution.record.session_id == 'session_123'
    assert resolution.accepted_tool_ids == frozenset({'call_1', 'call_2'})
    assert second_resolution.status == 'invalid'


@pytest.mark.asyncio
async def test_pending_turn_store_rejects_partial_batches_without_consuming_state() -> (
    None
):
    """Verify partial tool-result batches fail without consuming paused-turn state."""
    store = InMemoryPendingTurnStore(time_factory=lambda: 1000.0)
    await store.remember(
        record=PausedTurnRecord(
            session_id='session_123',
            tool_ids=frozenset({'call_1', 'call_2'}),
            request_model_id='gpt-5.4',
            runtime_model_id='copilot:gpt-5.4',
            auth_context_fingerprint='token:test',
            expires_at=1005.0,
        )
    )

    resolution = await store.resolve(tool_ids=('call_1',))
    stored_record = await store.get(session_id='session_123')

    assert resolution.status == 'invalid'
    assert stored_record is not None
    assert stored_record.tool_ids == frozenset({'call_1', 'call_2'})


@pytest.mark.asyncio
async def test_pending_turn_store_rejects_expected_session_mismatch() -> None:
    """Verify expected session mismatches fail before consuming paused-turn state."""
    store = InMemoryPendingTurnStore(time_factory=lambda: 1000.0)
    await store.remember(
        record=PausedTurnRecord(
            session_id='session_123',
            tool_ids=frozenset({'call_1'}),
            request_model_id='gpt-5.4',
            runtime_model_id='copilot:gpt-5.4',
            auth_context_fingerprint='token:test',
            expires_at=1005.0,
        )
    )

    resolution = await store.resolve(
        tool_ids=('call_1',),
        expected_session_id='session_other',
    )

    assert resolution.status == 'invalid'
    assert await store.get(session_id='session_123') is not None


@pytest.mark.asyncio
async def test_pending_turn_store_concurrent_resolution_allows_only_one_consumer() -> (
    None
):
    """Verify concurrent resolution attempts cannot consume one paused turn twice."""
    release_event = asyncio.Event()
    time_value = 1000.0

    def _time_factory() -> float:
        """Return a fixed wall-clock timestamp for deterministic expiry behavior."""
        return time_value

    store = InMemoryPendingTurnStore(time_factory=_time_factory)
    await store.remember(
        record=PausedTurnRecord(
            session_id='session_123',
            tool_ids=frozenset({'call_1'}),
            request_model_id='gpt-5.4',
            runtime_model_id='copilot:gpt-5.4',
            auth_context_fingerprint='token:test',
            expires_at=1005.0,
        )
    )

    async def _resolve_after_release() -> str:
        """Resolve one paused turn after both contenders are ready to race."""
        await release_event.wait()
        resolution = await store.resolve(tool_ids=('call_1',))
        return resolution.status

    first_task = asyncio.create_task(_resolve_after_release())
    second_task = asyncio.create_task(_resolve_after_release())
    await asyncio.sleep(0)
    release_event.set()
    statuses = sorted(await asyncio.gather(first_task, second_task))

    assert statuses == ['invalid', 'ready_to_resume']


@pytest.mark.asyncio
async def test_pending_turn_store_expires_and_calls_runtime_cleanup_once() -> None:
    """Verify store-owned expiry clears paused turns and invokes runtime cleanup."""
    expired_session_ids: list[str] = []
    current_time = 1000.0

    def _time_factory() -> float:
        """Return the controllable wall-clock timestamp for expiry checks."""
        return current_time

    async def _on_expire(session_id: str) -> None:
        """Record one expired session id passed through the runtime cleanup seam."""
        expired_session_ids.append(session_id)

    store = InMemoryPendingTurnStore(on_expire=_on_expire, time_factory=_time_factory)
    await store.remember(
        record=PausedTurnRecord(
            session_id='session_123',
            tool_ids=frozenset({'call_1'}),
            request_model_id='gpt-5.4',
            runtime_model_id='copilot:gpt-5.4',
            auth_context_fingerprint='token:test',
            expires_at=1000.0,
        )
    )

    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert await store.get(session_id='session_123') is None
    assert expired_session_ids == ['session_123']


@pytest.mark.asyncio
async def test_pending_turn_store_reports_historical_replay_when_enabled() -> None:
    """Verify unmatched tool ids can yield a replay-ignored resolution when allowed."""
    store = InMemoryPendingTurnStore()

    resolution = await store.resolve(
        tool_ids=('call_missing',),
        allow_historical_replay_ignored=True,
    )

    assert resolution.status == 'historical_replay_ignored'
