"""Unit tests for file-backed session lock leases."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from copilot_model_provider.storage import (
    FileBackedSessionLockManager,
    SessionLockOwnershipError,
    SessionLockRecord,
    SessionLockTimeoutError,
)
from tests.session_persistence_helpers import managed_scratch_directory


class _FakeClock:
    """Deterministic wall-clock and monotonic clock for lock timing tests."""

    def __init__(self) -> None:
        """Initialize the fake clock at a stable UTC timestamp."""
        self._current_time = datetime(2025, 1, 1, tzinfo=UTC)
        self._monotonic = 0.0

    def now(self) -> datetime:
        """Return the current fake wall-clock timestamp."""
        return self._current_time

    def monotonic(self) -> float:
        """Return the current fake monotonic timestamp."""
        return self._monotonic

    async def sleep(self, delay: float) -> None:
        """Advance the fake clocks without performing real event-loop sleeping."""
        self._current_time += timedelta(seconds=delay)
        self._monotonic += delay


@pytest.mark.asyncio
async def test_file_backed_session_lock_manager_acquires_and_releases_locks() -> None:
    """Verify that a held lease is visible and then removed after release."""
    with managed_scratch_directory('unit-session-locks') as scratch_directory:
        lock_manager = FileBackedSessionLockManager(scratch_directory / 'locks')

        held_lock = await lock_manager.acquire(
            conversation_id='conversation-1',
            owner='request-1',
        )
        inspected_record = lock_manager.inspect('conversation-1')
        await held_lock.release()

        assert inspected_record is not None
        assert inspected_record.owner == 'request-1'
        assert lock_manager.inspect('conversation-1') is None


@pytest.mark.asyncio
async def test_file_backed_session_lock_manager_times_out_while_lock_is_held() -> None:
    """Verify that competing callers receive a timeout while another owner holds the lock."""
    with managed_scratch_directory('unit-session-lock-timeout') as scratch_directory:
        fake_clock = _FakeClock()
        lock_manager = FileBackedSessionLockManager(
            scratch_directory / 'locks',
            clock=fake_clock.now,
            monotonic_clock=fake_clock.monotonic,
            sleep=fake_clock.sleep,
        )
        held_lock = await lock_manager.acquire(
            conversation_id='conversation-1',
            owner='request-1',
            timeout_seconds=0.5,
            lease_seconds=5.0,
        )

        with pytest.raises(SessionLockTimeoutError):
            await lock_manager.acquire(
                conversation_id='conversation-1',
                owner='request-2',
                timeout_seconds=0.4,
                lease_seconds=5.0,
            )

        await held_lock.release()


@pytest.mark.asyncio
async def test_file_backed_session_lock_manager_reclaims_expired_leases() -> None:
    """Verify that stale leases can be reclaimed by a later caller."""
    with managed_scratch_directory('unit-session-lock-expired') as scratch_directory:
        fake_clock = _FakeClock()
        lock_manager = FileBackedSessionLockManager(
            scratch_directory / 'locks',
            clock=fake_clock.now,
            monotonic_clock=fake_clock.monotonic,
            sleep=fake_clock.sleep,
        )
        original_lock = await lock_manager.acquire(
            conversation_id='conversation-1',
            owner='request-1',
            timeout_seconds=0.5,
            lease_seconds=0.2,
        )

        replacement_lock = await lock_manager.acquire(
            conversation_id='conversation-1',
            owner='request-2',
            timeout_seconds=0.5,
            lease_seconds=0.5,
        )

        with pytest.raises(SessionLockOwnershipError):
            await original_lock.release()

        assert replacement_lock.record.owner == 'request-2'
        await replacement_lock.release()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('timeout_seconds', 'lease_seconds', 'expected_message'),
    [
        (0.0, 30.0, 'timeout_seconds must be greater than 0'),
        (-1.0, 30.0, 'timeout_seconds must be greater than 0'),
        (1.0, 0.0, 'lease_seconds must be greater than 0'),
        (1.0, -1.0, 'lease_seconds must be greater than 0'),
    ],
)
async def test_file_backed_session_lock_manager_rejects_non_positive_timing_arguments(
    timeout_seconds: float,
    lease_seconds: float,
    expected_message: str,
) -> None:
    """Verify that lock acquisition rejects invalid timeout and lease settings."""
    with managed_scratch_directory(
        'unit-session-lock-invalid-arguments'
    ) as scratch_directory:
        lock_manager = FileBackedSessionLockManager(scratch_directory / 'locks')

        with pytest.raises(ValueError, match=expected_message):
            await lock_manager.acquire(
                conversation_id='conversation-1',
                owner='request-1',
                timeout_seconds=timeout_seconds,
                lease_seconds=lease_seconds,
            )


def test_file_backed_session_lock_manager_inspect_tolerates_disappearing_lock_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that concurrent lock removal is treated as an absent lease during inspection."""
    with managed_scratch_directory(
        'unit-session-lock-disappearing-inspect'
    ) as scratch_directory:
        lock_manager = FileBackedSessionLockManager(scratch_directory / 'locks')
        lock_path = lock_manager._lock_path('conversation-1')
        lock_path.write_text('{"conversation_id":"conversation-1"}\n', encoding='utf-8')
        original_read_text = type(lock_path).read_text

        def _read_text(path: object, *args: object, **kwargs: object) -> str:
            if path == lock_path:
                raise FileNotFoundError
            return original_read_text(path, *args, **kwargs)

        monkeypatch.setattr(type(lock_path), 'read_text', _read_text)

        assert lock_manager.inspect('conversation-1') is None


@pytest.mark.asyncio
async def test_file_backed_session_lock_manager_treats_invalid_lock_contents_as_lost_ownership() -> (
    None
):
    """Verify that corrupted lock files do not leak parsing errors during release."""
    with managed_scratch_directory(
        'unit-session-lock-invalid-release'
    ) as scratch_directory:
        lock_manager = FileBackedSessionLockManager(scratch_directory / 'locks')
        held_lock = await lock_manager.acquire(
            conversation_id='conversation-1',
            owner='request-1',
        )
        lock_path = lock_manager._lock_path('conversation-1')
        lock_path.write_text('{"conversation_id":"conversation-1"}\n', encoding='utf-8')

        assert lock_manager.inspect('conversation-1') is None

        with pytest.raises(SessionLockOwnershipError):
            await held_lock.release()


@pytest.mark.asyncio
async def test_file_backed_session_lock_manager_release_tolerates_disappearing_lock_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that release reports lost ownership when the lock file disappears mid-read."""
    with managed_scratch_directory(
        'unit-session-lock-disappearing-release'
    ) as scratch_directory:
        lock_manager = FileBackedSessionLockManager(scratch_directory / 'locks')
        record = SessionLockRecord(
            conversation_id='conversation-1',
            owner='request-1',
            token=uuid4().hex,
            acquired_at=datetime(2025, 1, 1, tzinfo=UTC),
            expires_at=datetime(2025, 1, 1, tzinfo=UTC) + timedelta(seconds=30),
        )
        lock_path = lock_manager._lock_path('conversation-1')
        lock_path.write_text(record.model_dump_json(indent=2), encoding='utf-8')
        original_read_text = type(lock_path).read_text

        def _read_text(path: object, *args: object, **kwargs: object) -> str:
            if path == lock_path:
                raise FileNotFoundError
            return original_read_text(path, *args, **kwargs)

        monkeypatch.setattr(type(lock_path), 'read_text', _read_text)

        with pytest.raises(SessionLockOwnershipError):
            await lock_manager.release(record)
