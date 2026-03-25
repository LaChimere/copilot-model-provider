"""Lease-based local locking for persistent conversation sessions."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from contextlib import suppress
from datetime import datetime, timedelta
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, Self, override
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from copilot_model_provider.storage.session_map import (
    build_storage_file_name,
    utc_now,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class SessionLockTimeoutError(RuntimeError):
    """Raised when a conversation lock cannot be acquired before the deadline."""


class SessionLockOwnershipError(RuntimeError):
    """Raised when a caller attempts to release a lock it no longer owns."""


class SessionLockRecord(BaseModel):
    """Serialized metadata describing an acquired session lock lease."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    conversation_id: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    token: str = Field(min_length=1)
    acquired_at: datetime
    expires_at: datetime

    def is_expired(self, *, reference_time: datetime | None = None) -> bool:
        """Report whether the lock lease has expired by ``reference_time``."""
        comparison_time = reference_time or utc_now()
        return self.expires_at <= comparison_time


class HeldSessionLock:
    """Async context manager that owns a single acquired session lock."""

    def __init__(
        self,
        *,
        manager: SessionLockManager,
        record: SessionLockRecord,
    ) -> None:
        """Store the manager callback and immutable lock record."""
        self._manager = manager
        self._record = record
        self._released = False

    @property
    def record(self) -> SessionLockRecord:
        """Expose the immutable record associated with the held lock."""
        return self._record

    async def release(self) -> None:
        """Release the held lock exactly once."""
        if self._released:
            return

        await self._manager.release(self._record)
        self._released = True

    async def __aenter__(self) -> Self:
        """Return the held lock so callers can use ``async with`` ergonomically."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        """Release the underlying lease when the async context finishes."""
        del exc_type, exc, traceback
        await self.release()


class SessionLockManager(ABC):
    """Abstract locking contract for serializing mutable session access."""

    @abstractmethod
    async def acquire(
        self,
        *,
        conversation_id: str,
        owner: str,
        timeout_seconds: float = 1.0,
        lease_seconds: float = 30.0,
    ) -> HeldSessionLock:
        """Acquire an exclusive lock for ``conversation_id``."""

    @abstractmethod
    def inspect(self, conversation_id: str) -> SessionLockRecord | None:
        """Return the current lock record for ``conversation_id`` when present."""

    @abstractmethod
    async def release(self, record: SessionLockRecord) -> None:
        """Release the lock described by ``record``."""


class FileBackedSessionLockManager(SessionLockManager):
    """Implement session locking via lease files stored on local disk."""

    def __init__(
        self,
        root_directory: Path | str,
        *,
        poll_interval_seconds: float = 0.01,
        clock: Callable[[], datetime] = utc_now,
        monotonic_clock: Callable[[], float] = monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Initialize the lock manager with a filesystem root and timing hooks."""
        self._root_directory = Path(root_directory)
        self._root_directory.mkdir(parents=True, exist_ok=True)
        self._poll_interval_seconds = poll_interval_seconds
        self._clock = clock
        self._monotonic_clock = monotonic_clock
        self._sleep = sleep

    @override
    async def acquire(
        self,
        *,
        conversation_id: str,
        owner: str,
        timeout_seconds: float = 1.0,
        lease_seconds: float = 30.0,
    ) -> HeldSessionLock:
        """Acquire an exclusive lease for ``conversation_id``.

        Args:
            conversation_id: External conversation identifier to guard.
            owner: Request- or worker-level owner string recorded in the lease.
            timeout_seconds: Maximum amount of time to wait for the lock.
            lease_seconds: Duration after which an abandoned lock is considered stale.

        Returns:
            A ``HeldSessionLock`` that releases the lease when requested.

        Raises:
            ValueError: If any timing argument is not strictly positive.
            SessionLockTimeoutError: If the lock stays owned past the timeout.

        """
        if timeout_seconds <= 0:
            msg = 'timeout_seconds must be greater than 0'
            raise ValueError(msg)
        if lease_seconds <= 0:
            msg = 'lease_seconds must be greater than 0'
            raise ValueError(msg)

        deadline = self._monotonic_clock() + timeout_seconds
        while True:
            now = self._clock()
            record = SessionLockRecord(
                conversation_id=conversation_id,
                owner=owner,
                token=uuid4().hex,
                acquired_at=now,
                expires_at=now + timedelta(seconds=lease_seconds),
            )
            if self._try_create(record):
                return HeldSessionLock(manager=self, record=record)

            existing_record = self.inspect(conversation_id)
            if (
                existing_record is not None
                and existing_record.is_expired(reference_time=now)
                and self._delete_lock_file(
                    conversation_id=conversation_id,
                    expected_token=existing_record.token,
                )
            ):
                continue

            if self._monotonic_clock() >= deadline:
                msg = 'Timed out while waiting to acquire the conversation lock.'
                raise SessionLockTimeoutError(msg)

            await self._sleep(self._poll_interval_seconds)

    @override
    def inspect(self, conversation_id: str) -> SessionLockRecord | None:
        """Return the current lock lease for ``conversation_id`` when present."""
        return self._read_lock_record(self._lock_path(conversation_id))

    @override
    async def release(self, record: SessionLockRecord) -> None:
        """Release the lock described by ``record``.

        Raises:
            SessionLockOwnershipError: If the on-disk lock no longer matches the
                caller's lease token.

        """
        if not self._delete_lock_file(
            conversation_id=record.conversation_id,
            expected_token=record.token,
        ):
            msg = 'The session lock is no longer owned by the releasing caller.'
            raise SessionLockOwnershipError(msg)

    def _try_create(self, record: SessionLockRecord) -> bool:
        """Attempt to create the lock file for ``record`` atomically."""
        path = self._lock_path(record.conversation_id)
        try:
            with path.open('x', encoding='utf-8') as handle:
                handle.write(f'{record.model_dump_json(indent=2)}\n')
        except FileExistsError:
            return False
        except Exception:
            with suppress(FileNotFoundError):
                path.unlink()
            raise

        return True

    def _read_lock_record(self, path: Path) -> SessionLockRecord | None:
        """Read ``path`` while tolerating concurrent lock-file replacement or removal."""
        try:
            payload = path.read_text(encoding='utf-8')
        except FileNotFoundError:
            return None

        try:
            return SessionLockRecord.model_validate_json(payload)
        except ValidationError:
            return None

    def _delete_lock_file(self, *, conversation_id: str, expected_token: str) -> bool:
        """Delete the lock file when it still belongs to ``expected_token``."""
        path = self._lock_path(conversation_id)
        record = self._read_lock_record(path)
        if record is None or record.token != expected_token:
            return False

        try:
            path.unlink()
        except FileNotFoundError:
            return False

        return True

    def _lock_path(self, conversation_id: str) -> Path:
        """Build the storage path for ``conversation_id``."""
        return self._root_directory / build_storage_file_name(conversation_id)
