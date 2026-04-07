"""Helpers for model-catalog snapshots derived from live runtime discovery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from copilot_model_provider.core.models import ModelCatalogEntry, RuntimeDiscoveredModel

if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclass(frozen=True, slots=True)
class ModelCatalog:
    """Store and validate one public model-catalog snapshot."""

    entries: tuple[ModelCatalogEntry, ...]

    def __post_init__(self) -> None:
        """Ensure that each public alias is unique inside the catalog."""
        aliases = [entry.alias for entry in self.entries]
        if len(set(aliases)) != len(aliases):
            msg = 'Model catalog aliases must be unique'
            raise ValueError(msg)

    def list_entries(self) -> tuple[ModelCatalogEntry, ...]:
        """Return the catalog entries in their stable public order.

        Returns:
            A tuple of ``ModelCatalogEntry`` values suitable for listing or
            deterministic test assertions.

        """
        return self.entries

    def get_entry(self, *, alias: str) -> ModelCatalogEntry | None:
        """Look up a catalog entry by its public model alias.

        Args:
            alias: The public alias exposed through the compatibility surface.

        Returns:
            The matching ``ModelCatalogEntry`` when it exists, otherwise ``None``.

        """
        for entry in self.entries:
            if entry.alias == alias:
                return entry

        return None


def build_live_model_catalog(
    *,
    runtime: str,
    owned_by: str,
    model_ids: Iterable[str],
) -> ModelCatalog:
    """Build one catalog snapshot from live runtime model identifiers.

    Args:
        runtime: Stable runtime name that should back every exposed model.
        owned_by: Owner label exposed through the compatibility surface.
        model_ids: Visible runtime model identifiers for the current auth context.

    Returns:
        A ``ModelCatalog`` that exposes each runtime model identifier as the same
        public model identifier.

    """
    return build_live_model_catalog_from_models(
        runtime=runtime,
        owned_by=owned_by,
        models=(RuntimeDiscoveredModel(id=model_id) for model_id in model_ids),
    )


def build_live_model_catalog_from_models(
    *,
    runtime: str,
    owned_by: str,
    models: Iterable[RuntimeDiscoveredModel],
) -> ModelCatalog:
    """Build one catalog snapshot from normalized runtime model descriptors.

    Args:
        runtime: Stable runtime name that should back every exposed model.
        owned_by: Owner label exposed through the compatibility surface.
        models: Normalized runtime model descriptors visible to the current auth
            context.

    Returns:
        A ``ModelCatalog`` that preserves each runtime model identifier plus any
        provider-owned metadata captured during runtime model discovery.

    """
    return ModelCatalog(
        entries=tuple(
            ModelCatalogEntry(
                alias=model.id,
                runtime=runtime,
                owned_by=owned_by,
                runtime_model_id=model.id,
                created=model.created,
                copilot=model.copilot,
            )
            for model in models
        )
    )
