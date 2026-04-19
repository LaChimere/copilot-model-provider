"""Shared paused-turn bookkeeping for tool-aware continuation flows."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Literal, Protocol, override, runtime_checkable

import structlog
from pydantic import BaseModel, ConfigDict, Field

from copilot_model_provider.core.routing import build_auth_context_cache_key

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Collection

_logger = structlog.get_logger(__name__)


class PausedTurnContinuationPolicy(BaseModel):
    """Policy describing how one paused turn may be resumed."""

    model_config = ConfigDict(frozen=True)

    kind: Literal['full_batch_required'] = 'full_batch_required'


class PausedTurnResolution(BaseModel):
    """Outcome produced when the store resolves and consumes one paused turn."""

    model_config = ConfigDict(frozen=True)

    status: Literal[
        'historical_replay_ignored', 'invalid', 'ready_to_resume', 'expired'
    ]
    record: PausedTurnRecord | None = None
    accepted_tool_ids: frozenset[str] = Field(default_factory=frozenset)


class PausedTurnRecord(BaseModel):
    """Provider-owned bookkeeping for one paused interactive continuation turn."""

    model_config = ConfigDict(frozen=True)

    session_id: str = Field(min_length=1)
    tool_ids: frozenset[str] = Field(default_factory=frozenset)
    request_model_id: str = Field(min_length=1)
    runtime_model_id: str = Field(min_length=1)
    auth_context_fingerprint: str = Field(min_length=1)
    expires_at: float
    continuation_policy: PausedTurnContinuationPolicy = Field(
        default_factory=PausedTurnContinuationPolicy
    )


def build_auth_context_fingerprint(*, runtime_auth_token: str | None) -> str:
    """Build the paused-turn auth-context fingerprint for one request.

    Args:
        runtime_auth_token: Request-scoped runtime auth token, if present.

    Returns:
        The same key shape used by the model-router auth-context cache.

    """
    return build_auth_context_cache_key(runtime_auth_token=runtime_auth_token)


def build_paused_turn_record(
    *,
    session_id: str,
    tool_ids: Collection[str],
    request_model_id: str,
    runtime_model_id: str,
    runtime_auth_token: str | None,
    expires_at: float,
) -> PausedTurnRecord:
    """Build one paused-turn record from runtime-owned continuation context.

    Args:
        session_id: Runtime interactive session identifier reused on continuation.
        tool_ids: Pending external tool-call identifiers that must be satisfied.
        request_model_id: Northbound request model id that opened the paused turn.
        runtime_model_id: Resolved runtime model id selected for that turn.
        runtime_auth_token: Request-scoped runtime auth token, if present.
        expires_at: Wall-clock expiry timestamp for this paused turn.

    Returns:
        A paused-turn record carrying only the base-slice shared semantic-core state.

    """
    return PausedTurnRecord(
        session_id=session_id,
        tool_ids=frozenset(tool_ids),
        request_model_id=request_model_id,
        runtime_model_id=runtime_model_id,
        auth_context_fingerprint=build_auth_context_fingerprint(
            runtime_auth_token=runtime_auth_token
        ),
        expires_at=expires_at,
    )


@runtime_checkable
class PendingTurnStoreProtocol(Protocol):
    """Protocol for paused-turn bookkeeping shared across compatibility routes."""

    async def remember(self, *, record: PausedTurnRecord) -> None:
        """Remember one paused turn and schedule its expiry cleanup."""
        ...

    async def get(self, *, session_id: str) -> PausedTurnRecord | None:
        """Return one paused-turn record by session id when it is still pending."""
        ...

    async def discard(self, *, session_id: str) -> PausedTurnRecord | None:
        """Remove one paused turn without attempting to resolve it for continuation."""
        ...

    async def resolve(
        self,
        *,
        tool_ids: Collection[str],
        expected_session_id: str | None = None,
        allow_historical_replay_ignored: bool = False,
    ) -> PausedTurnResolution:
        """Resolve and atomically consume one paused turn for continuation reuse."""
        ...

    async def close(self) -> None:
        """Cancel store-owned expiry tasks before disposing the in-memory store."""
        ...


class InMemoryPendingTurnStore(PendingTurnStoreProtocol):
    """In-memory paused-turn store with atomic single-consume semantics."""

    def __init__(
        self,
        *,
        on_expire: Callable[[str], Awaitable[None]] | None = None,
        time_factory: Callable[[], float] = time.time,
    ) -> None:
        """Initialize the store with optional runtime cleanup for expired turns.

        Args:
            on_expire: Optional async callback invoked once per expired session id
                after the paused turn has been removed from in-memory bookkeeping.
            time_factory: Wall-clock time source used for expiry comparisons.

        """
        self._on_expire = on_expire
        self._time_factory = time_factory
        self._records_by_session_id: dict[str, PausedTurnRecord] = {}
        self._session_id_by_tool_id: dict[str, str] = {}
        self._expiry_tasks_by_session_id: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    @override
    async def remember(self, *, record: PausedTurnRecord) -> None:
        """Remember one paused turn and refresh its store-owned expiry task."""
        async with self._lock:
            self._discard_locked(session_id=record.session_id)
            self._records_by_session_id[record.session_id] = record
            for tool_id in record.tool_ids:
                self._session_id_by_tool_id[tool_id] = record.session_id
            self._schedule_expiry_locked(session_id=record.session_id, record=record)

    @override
    async def get(self, *, session_id: str) -> PausedTurnRecord | None:
        """Return one paused-turn record when it is still pending in the store."""
        async with self._lock:
            return self._records_by_session_id.get(session_id)

    @override
    async def discard(self, *, session_id: str) -> PausedTurnRecord | None:
        """Remove one paused-turn record without resolving it for continuation."""
        async with self._lock:
            return self._discard_locked(session_id=session_id)

    @override
    async def resolve(
        self,
        *,
        tool_ids: Collection[str],
        expected_session_id: str | None = None,
        allow_historical_replay_ignored: bool = False,
    ) -> PausedTurnResolution:
        """Resolve and atomically consume one paused turn for continuation reuse.

        Args:
            tool_ids: Submitted tool-result identifiers relevant to this continuation.
            expected_session_id: Optional route-specific session expectation used to
                reject mismatched lookup paths.
            allow_historical_replay_ignored: Whether unmatched tool ids should yield
                a replay-ignored result instead of an invalid result.

        Returns:
            A paused-turn resolution outcome that either yields a consumed record or
            reports why no pending turn may be resumed.

        """
        submitted_tool_ids = frozenset(tool_ids)
        expired_session_id: str | None = None
        expired_resolution: PausedTurnResolution | None = None
        async with self._lock:
            matched_tool_ids = frozenset(
                tool_id
                for tool_id in submitted_tool_ids
                if tool_id in self._session_id_by_tool_id
            )
            if not matched_tool_ids:
                return PausedTurnResolution(
                    status=(
                        'historical_replay_ignored'
                        if allow_historical_replay_ignored
                        else 'invalid'
                    )
                )

            matched_session_ids = {
                self._session_id_by_tool_id[tool_id] for tool_id in matched_tool_ids
            }
            if len(matched_session_ids) != 1:
                return PausedTurnResolution(status='invalid')

            session_id = next(iter(matched_session_ids))
            if expected_session_id is not None and expected_session_id != session_id:
                return PausedTurnResolution(status='invalid')

            record = self._records_by_session_id.get(session_id)
            if record is None:
                return PausedTurnResolution(status='invalid')

            if self._time_factory() >= record.expires_at:
                self._discard_locked(session_id=session_id)
                expired_session_id = session_id
                expired_resolution = PausedTurnResolution(
                    status='expired',
                    record=record,
                )
            elif matched_tool_ids != record.tool_ids:
                return PausedTurnResolution(status='invalid')
            else:
                consumed_record = self._discard_locked(session_id=session_id)
                if consumed_record is None:
                    return PausedTurnResolution(status='invalid')

                return PausedTurnResolution(
                    status='ready_to_resume',
                    record=consumed_record,
                    accepted_tool_ids=matched_tool_ids,
                )

        await self._call_on_expire(session_id=expired_session_id)
        return expired_resolution

    @override
    async def close(self) -> None:
        """Cancel any outstanding expiry tasks before discarding the store."""
        async with self._lock:
            expiry_tasks = tuple(self._expiry_tasks_by_session_id.values())
            self._expiry_tasks_by_session_id.clear()
            self._records_by_session_id.clear()
            self._session_id_by_tool_id.clear()
        for expiry_task in expiry_tasks:
            expiry_task.cancel()
        await asyncio.gather(*expiry_tasks, return_exceptions=True)

    async def _expire_after_deadline(self, *, session_id: str) -> None:
        """Expire one paused turn when its deadline elapses."""
        async with self._lock:
            record = self._records_by_session_id.get(session_id)
            if record is None:
                return
            delay_seconds = max(record.expires_at - self._time_factory(), 0.0)

        try:
            await asyncio.sleep(delay_seconds)
        except asyncio.CancelledError:
            return

        async with self._lock:
            record = self._records_by_session_id.get(session_id)
            if record is None:
                return
            if self._time_factory() < record.expires_at:
                self._schedule_expiry_locked(session_id=session_id, record=record)
                return
            self._discard_locked(session_id=session_id)

        _logger.info(
            'pending_turn_expired',
            session_id=session_id,
            ttl_expires_at=record.expires_at,
            tool_ids=sorted(record.tool_ids),
        )
        await self._call_on_expire(session_id=session_id)

    def _schedule_expiry_locked(
        self,
        *,
        session_id: str,
        record: PausedTurnRecord,
    ) -> None:
        """Refresh the expiry task for one remembered paused turn."""
        existing_task = self._expiry_tasks_by_session_id.pop(session_id, None)
        if existing_task is not None:
            existing_task.cancel()
        self._expiry_tasks_by_session_id[session_id] = asyncio.create_task(
            self._expire_after_deadline(session_id=session_id)
        )
        _logger.info(
            'pending_turn_remembered',
            session_id=session_id,
            tool_ids=sorted(record.tool_ids),
            ttl_expires_at=record.expires_at,
        )

    def _discard_locked(self, *, session_id: str) -> PausedTurnRecord | None:
        """Remove one paused turn from store-owned state under the store lock."""
        record = self._records_by_session_id.pop(session_id, None)
        expiry_task = self._expiry_tasks_by_session_id.pop(session_id, None)
        if expiry_task is not None:
            expiry_task.cancel()
        if record is None:
            return None
        for tool_id in record.tool_ids:
            mapped_session_id = self._session_id_by_tool_id.get(tool_id)
            if mapped_session_id == session_id:
                self._session_id_by_tool_id.pop(tool_id, None)
        return record

    async def _call_on_expire(self, *, session_id: str) -> None:
        """Invoke the optional runtime cleanup callback for one expired session."""
        if self._on_expire is None:
            return
        await self._on_expire(session_id)
