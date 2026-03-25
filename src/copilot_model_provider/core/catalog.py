"""Service-owned model catalog helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from copilot_model_provider.core.models import ModelCatalogEntry

if TYPE_CHECKING:
    from copilot_model_provider.config import ProviderSettings


@dataclass(frozen=True, slots=True)
class ModelCatalog:
    """Store and validate the service-owned set of public model aliases."""

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


def create_default_model_catalog(*, settings: ProviderSettings) -> ModelCatalog:
    """Build the repository's default service-owned model catalog.

    Args:
        settings: Application settings that supply the default runtime name and
            the owner label exposed through the compatibility surface.

    Returns:
        A ``ModelCatalog`` containing the stable public aliases served by the
        application before runtime execution is implemented.

    """
    return ModelCatalog(
        entries=(
            ModelCatalogEntry(
                alias='default',
                runtime=settings.default_runtime,
                owned_by=settings.app_name,
                runtime_model_id=f'{settings.default_runtime}-default',
            ),
            ModelCatalogEntry(
                alias='fast',
                runtime=settings.default_runtime,
                owned_by=settings.app_name,
                runtime_model_id=f'{settings.default_runtime}-fast',
            ),
        )
    )
