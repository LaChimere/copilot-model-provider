"""Integration checks for file-backed session lock coordination."""

from __future__ import annotations

import asyncio

import pytest

from copilot_model_provider.storage import FileBackedSessionLockManager
from tests.session_persistence_helpers import managed_scratch_directory


@pytest.mark.asyncio
async def test_session_locking_serializes_handoffs_between_managers() -> None:
    """Verify that separate lock managers coordinate access through shared storage."""
    with managed_scratch_directory('integration-session-locks') as scratch_directory:
        first_manager = FileBackedSessionLockManager(scratch_directory / 'locks')
        second_manager = FileBackedSessionLockManager(scratch_directory / 'locks')

        first_lock = await first_manager.acquire(
            conversation_id='conversation-1',
            owner='request-1',
            timeout_seconds=0.5,
            lease_seconds=5.0,
        )

        async def _acquire_second_lock() -> str:
            """Wait for the second manager to acquire the same conversation lock."""
            second_lock = await second_manager.acquire(
                conversation_id='conversation-1',
                owner='request-2',
                timeout_seconds=0.5,
                lease_seconds=5.0,
            )
            async with second_lock:
                return second_lock.record.owner

        acquisition_task = asyncio.create_task(_acquire_second_lock())
        await asyncio.sleep(0.02)
        assert acquisition_task.done() is False

        await first_lock.release()

        assert await acquisition_task == 'request-2'
