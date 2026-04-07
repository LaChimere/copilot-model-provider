"""Runtime protocol contracts for the provider scaffold."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from copilot_model_provider.core.models import RuntimeDiscoveredModel

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from copilot.generated.session_events import SessionEvent

    from copilot_model_provider.core.models import (
        CanonicalChatRequest,
        ResolvedRoute,
        RuntimeCompletion,
        RuntimeHealth,
    )


@dataclass(frozen=True, slots=True)
class RuntimeEventStream:
    """Runtime-owned streaming session metadata and event iterator.

    Attributes:
        session_id: The active Copilot session identifier created for the current
            stream when the runtime exposes one, otherwise ``None``.
        events: Async iterator that yields Copilot SDK session events in the order
            required by the streaming convergence layer.
        close: Optional cleanup callback invoked when the HTTP layer must abort
            the stream before event consumption begins.

    """

    session_id: str | None
    events: AsyncIterator[SessionEvent]
    close: Callable[[], Awaitable[None]] | None = None


@runtime_checkable
class RuntimeProtocol(Protocol):
    """Protocol contract for provider runtime backends.

    The provider's composition root and API routes depend on this protocol rather
    than on a specific runtime class so that runtime implementations remain
    substitutable without requiring inheritance from a framework-owned base class.
    """

    @property
    def runtime_name(self) -> str:
        """Return the stable runtime identifier exposed by this runtime."""
        ...

    def default_route(self) -> ResolvedRoute:
        """Return the default route metadata for the runtime backend."""
        ...

    async def check_health(self) -> RuntimeHealth:
        """Return runtime health metadata for internal diagnostics."""
        ...

    async def list_models(
        self,
        *,
        runtime_auth_token: str | None = None,
    ) -> tuple[RuntimeDiscoveredModel, ...]:
        """Return normalized live runtime model descriptors for one auth context.

        Args:
            runtime_auth_token: Optional request-scoped bearer token that should
                override the runtime's configured default auth context for this
                discovery call.

        Returns:
            A stable, de-duplicated tuple of normalized runtime model descriptors
            visible to the supplied auth context.

        """
        model_ids = await self.list_model_ids(runtime_auth_token=runtime_auth_token)
        return tuple(RuntimeDiscoveredModel(id=model_id) for model_id in model_ids)

    async def list_model_ids(
        self,
        *,
        runtime_auth_token: str | None = None,
    ) -> tuple[str, ...]:
        """Return the live runtime model identifiers for one auth context.

        Args:
            runtime_auth_token: Optional request-scoped bearer token that should
                override the runtime's configured default auth context for this
                discovery call.

        Returns:
            A stable, de-duplicated tuple of runtime model identifiers visible to
            the supplied auth context.

        """
        ...

    async def complete_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeCompletion:
        """Execute a normalized non-streaming chat request."""
        ...

    async def stream_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeEventStream:
        """Execute a normalized streaming chat request."""
        ...
