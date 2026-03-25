"""Shared session-convergence helpers for chat execution paths."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from copilot_model_provider.core.errors import ProviderError
from copilot_model_provider.storage import (
    HeldSessionLock,
    SessionLockManager,
    SessionMap,
    SessionMapEntry,
)

if TYPE_CHECKING:
    from copilot_model_provider.core.models import CanonicalChatRequest, ResolvedRoute

_DEFAULT_LOCK_TIMEOUT_SECONDS = 1.0
_DEFAULT_LOCK_LEASE_SECONDS = 30.0
_CONVERSATION_ID_HEADER_NAME = 'X-Copilot-Conversation-Id'


@dataclass(frozen=True, slots=True)
class ManagedExecutionSession:
    """Execution-scoped session state shared by chat convergence code.

    Attributes:
        request: Canonical request enriched with any resumed Copilot session ID.
        route: Resolved runtime route for the current chat request.
        held_lock: Active held lock for sessional execution, or ``None`` for
            stateless requests.

    """

    request: CanonicalChatRequest
    route: ResolvedRoute
    held_lock: HeldSessionLock | None = None


async def prepare_execution_session(
    *,
    request: CanonicalChatRequest,
    route: ResolvedRoute,
    session_map: SessionMap | None,
    session_lock_manager: SessionLockManager | None,
) -> ManagedExecutionSession:
    """Prepare session state for one chat execution request.

    Args:
        request: Canonical request normalized from the northbound API payload.
        route: Resolved route metadata for the requested model alias.
        session_map: Optional persistence backend used for session-backed routes.
        session_lock_manager: Optional lock manager used to serialize mutable
            session-backed routes.

    Returns:
        A ``ManagedExecutionSession`` containing the enriched request and any held
        conversation lock needed for the execution.

    Raises:
        ProviderError: If a sessional route is missing the conversation header or
            the application is missing required session infrastructure.

    """
    if route.session_mode == 'stateless':
        return ManagedExecutionSession(request=request, route=route)

    if request.conversation_id is None:
        raise ProviderError(
            code='conversation_id_required',
            message=(
                'Sessional chat requests require the '
                f'{_CONVERSATION_ID_HEADER_NAME} header.'
            ),
            status_code=400,
        )

    if session_map is None or session_lock_manager is None:
        raise ProviderError(
            code='session_storage_unavailable',
            message='Session persistence is not configured for this route.',
            status_code=500,
        )

    held_lock = await session_lock_manager.acquire(
        conversation_id=request.conversation_id,
        owner=request.request_id or request.conversation_id,
        timeout_seconds=_DEFAULT_LOCK_TIMEOUT_SECONDS,
        lease_seconds=_DEFAULT_LOCK_LEASE_SECONDS,
    )
    existing_entry = session_map.get(request.conversation_id)
    session_id = (
        existing_entry.copilot_session_id if existing_entry is not None else None
    )
    enriched_request = request.model_copy(update={'session_id': session_id})
    return ManagedExecutionSession(
        request=enriched_request,
        route=route,
        held_lock=held_lock,
    )


def persist_execution_session(
    *,
    managed_session: ManagedExecutionSession,
    session_map: SessionMap | None,
    runtime_name: str,
    runtime_model_id: str | None,
    session_id: str | None,
) -> None:
    """Persist the active Copilot session for a session-backed execution.

    Args:
        managed_session: Execution-scoped session data returned by
            ``prepare_execution_session``.
        session_map: Persistence backend used for conversation-to-session lookup.
        runtime_name: Canonical runtime name used for the executed route.
        runtime_model_id: Concrete runtime model identifier used for execution.
        session_id: Copilot session identifier returned by the runtime adapter.

    """
    conversation_id = managed_session.request.conversation_id
    if (
        managed_session.route.session_mode != 'sessional'
        or conversation_id is None
        or session_id is None
        or session_map is None
    ):
        return

    session_map.put(
        SessionMapEntry(
            conversation_id=conversation_id,
            copilot_session_id=session_id,
            runtime_name=runtime_name,
            runtime_model_id=runtime_model_id,
            execution_mode='sessional',
        )
    )


async def release_execution_session(
    *,
    managed_session: ManagedExecutionSession,
) -> None:
    """Release any held session lock associated with one execution request.

    Args:
        managed_session: Execution-scoped session data returned by
            ``prepare_execution_session``.

    """
    if managed_session.held_lock is not None:
        await managed_session.held_lock.release()
