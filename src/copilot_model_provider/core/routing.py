"""Routing helpers that translate public model aliases into runtime metadata."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, override, runtime_checkable

from copilot_model_provider.core.errors import ProviderError
from copilot_model_provider.core.models import (
    OpenAIModelCard,
    OpenAIModelListResponse,
    ResolvedRoute,
)

if TYPE_CHECKING:
    from copilot_model_provider.core.catalog import ModelCatalog


@runtime_checkable
class ModelRouterProtocol(Protocol):
    """Protocol contract for public-model listing and alias resolution."""

    @property
    def model_catalog(self) -> ModelCatalog:
        """Return the model catalog backing this routing policy."""
        ...

    def list_models_response(self) -> OpenAIModelListResponse:
        """Build the public model-list response for the compatibility layer."""
        ...

    def resolve_model(self, *, alias: str) -> ResolvedRoute:
        """Resolve one public model alias into runtime routing metadata."""
        ...


class ModelRouter(ModelRouterProtocol):
    """Resolve service-owned public model aliases into runtime routing metadata."""

    def __init__(self, *, model_catalog: ModelCatalog) -> None:
        """Create a router bound to a validated model catalog.

        Args:
            model_catalog: The service-owned catalog that defines public aliases
                and the runtime metadata they should map to.

        """
        self._model_catalog = model_catalog

    @property
    @override
    def model_catalog(self) -> ModelCatalog:
        """Return the catalog backing this router.

        Returns:
            The ``ModelCatalog`` used for public model listing and alias
            resolution.

        """
        return self._model_catalog

    @override
    def list_models_response(self) -> OpenAIModelListResponse:
        """Build the OpenAI-compatible model listing response.

        Returns:
            An ``OpenAIModelListResponse`` containing one card per public alias
            in the catalog, preserving the catalog's stable ordering.

        """
        return OpenAIModelListResponse(
            data=[
                OpenAIModelCard(
                    id=entry.alias,
                    created=entry.created,
                    owned_by=entry.owned_by,
                )
                for entry in self.model_catalog.list_entries()
            ]
        )

    @override
    def resolve_model(self, *, alias: str) -> ResolvedRoute:
        """Resolve a public model alias into runtime routing metadata.

        Args:
            alias: The public alias requested by a compatibility-layer client.

        Returns:
            A ``ResolvedRoute`` describing which runtime and runtime model ID
            should handle requests for the alias.

        Raises:
            ProviderError: If the alias is unknown to the service-owned catalog.

        """
        entry = self.model_catalog.get_entry(alias=alias)
        if entry is None:
            msg = f'Unknown model alias: {alias!r}'
            raise ProviderError(
                code='model_not_found',
                message=msg,
                status_code=404,
            )

        return ResolvedRoute(
            runtime=entry.runtime,
            runtime_model_id=entry.runtime_model_id,
        )
