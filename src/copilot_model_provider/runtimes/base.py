"""Base runtime adapter contracts for the provider scaffold."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, override

from copilot_model_provider.core.errors import ProviderError
from copilot_model_provider.core.models import (
    CanonicalChatRequest,
    ResolvedRoute,
    RuntimeCompletion,
    RuntimeHealth,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from copilot.generated.session_events import SessionEvent


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


class RuntimeAdapter(ABC):
    """Abstract contract for provider runtime backends."""

    def __init__(self, *, runtime_name: str) -> None:
        """Initialize the adapter with a stable runtime name."""
        self._runtime_name = runtime_name

    @property
    def runtime_name(self) -> str:
        """Return the stable runtime identifier exposed by this adapter."""
        return self._runtime_name

    @abstractmethod
    def default_route(self) -> ResolvedRoute:
        """Return the default route metadata for the runtime backend."""

    @abstractmethod
    async def check_health(self) -> RuntimeHealth:
        """Return runtime health metadata for internal diagnostics."""

    @abstractmethod
    async def complete_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeCompletion:
        """Execute a normalized non-streaming chat request."""

    @abstractmethod
    async def stream_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeEventStream:
        """Execute a normalized streaming chat request."""


class ScaffoldRuntimeAdapter(RuntimeAdapter):
    """Non-executing runtime used during the scaffold phase."""

    def __init__(self) -> None:
        """Initialize the scaffold adapter."""
        super().__init__(runtime_name='copilot')

    @override
    def default_route(self) -> ResolvedRoute:
        """Return the placeholder route used during the scaffold phase."""
        return ResolvedRoute(runtime=self.runtime_name)

    @override
    async def check_health(self) -> RuntimeHealth:
        """Report scaffold health without claiming execution support."""
        return RuntimeHealth(
            runtime=self.runtime_name,
            available=False,
            detail='Scaffold only; runtime execution is not implemented yet.',
        )

    @override
    async def complete_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeCompletion:
        """Reject chat execution while the scaffold adapter is active."""
        del request, route
        raise ProviderError(
            code='runtime_not_available',
            message='Chat execution is not available for the scaffold runtime.',
            status_code=503,
        )

    @override
    async def stream_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeEventStream:
        """Reject streaming execution while the scaffold adapter is active."""
        del request, route
        raise ProviderError(
            code='runtime_not_available',
            message='Chat execution is not available for the scaffold runtime.',
            status_code=503,
        )
