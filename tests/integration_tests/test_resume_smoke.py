"""Smoke tests for the session persistence storage and locking primitives."""

from __future__ import annotations

import pytest

from copilot_model_provider.storage import (
    FileBackedSessionLockManager,
    FileBackedSessionMap,
)
from tests.session_persistence_helpers import (
    build_session_map_entry,
    managed_scratch_directory,
)


@pytest.mark.asyncio
async def test_resume_smoke_supports_lock_then_resume_after_restart() -> None:
    """Verify that persisted mappings and lock handoff survive a restart-like cycle."""
    with managed_scratch_directory('integration-resume-smoke') as scratch_directory:
        initial_map = FileBackedSessionMap(scratch_directory / 'session-map')
        initial_locks = FileBackedSessionLockManager(scratch_directory / 'locks')

        first_lock = await initial_locks.acquire(
            conversation_id='conversation-smoke',
            owner='request-1',
            timeout_seconds=0.5,
            lease_seconds=5.0,
        )
        async with first_lock:
            stored_entry = initial_map.put(
                build_session_map_entry(
                    conversation_id='conversation-smoke',
                    copilot_session_id='copilot-session-smoke',
                )
            )

        restarted_map = FileBackedSessionMap(scratch_directory / 'session-map')
        restarted_locks = FileBackedSessionLockManager(scratch_directory / 'locks')
        second_lock = await restarted_locks.acquire(
            conversation_id='conversation-smoke',
            owner='request-2',
            timeout_seconds=0.5,
            lease_seconds=5.0,
        )
        async with second_lock:
            resumed_entry = restarted_map.get('conversation-smoke')

        assert resumed_entry is not None
        assert resumed_entry.copilot_session_id == stored_entry.copilot_session_id
        assert resumed_entry.created_at == stored_entry.created_at
