"""Base runtime adapter contracts for the provider scaffold."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import override

from copilot_model_provider.core.models import ResolvedRoute, RuntimeHealth


class RuntimeAdapter(ABC):
    """Abstract contract for provider runtime backends."""

    def __init__(self, *, runtime_name: str) -> None:
        """Initialize the adapter with a stable runtime name."""
        self._runtime_name = runtime_name

    @property
    def runtime_name(self) -> str:
        """Return the stable runtime identifier exposed by this adapter.

        Returns:
            The canonical runtime name used in routing, diagnostics, and
            internal health responses.

        """
        return self._runtime_name

    @abstractmethod
    def default_route(self) -> ResolvedRoute:
        """Return the default route metadata for the runtime backend.

        Returns:
            A ``ResolvedRoute`` describing the runtime and session mode that
            should be used when no higher-level routing decision exists.

        """

    @abstractmethod
    async def check_health(self) -> RuntimeHealth:
        """Return runtime health metadata for internal diagnostics.

        Returns:
            A ``RuntimeHealth`` payload describing whether the backend is
            available and any diagnostic detail worth surfacing internally.

        """


class ScaffoldRuntimeAdapter(RuntimeAdapter):
    """Non-executing runtime used during the scaffold phase."""

    def __init__(self) -> None:
        """Initialize the scaffold adapter."""
        super().__init__(runtime_name='copilot')

    @override
    def default_route(self) -> ResolvedRoute:
        """Return the placeholder route used during the scaffold phase.

        Returns:
            A stateless route bound to the scaffold's ``copilot`` runtime name.

        """
        return ResolvedRoute(runtime=self.runtime_name, session_mode='stateless')

    @override
    async def check_health(self) -> RuntimeHealth:
        """Report scaffold health without claiming execution support.

        Returns:
            A ``RuntimeHealth`` object that makes it explicit the scaffold can
            boot successfully even though real runtime execution is deferred.

        """
        return RuntimeHealth(
            runtime=self.runtime_name,
            available=False,
            detail='Scaffold only; runtime execution is not implemented yet.',
        )
