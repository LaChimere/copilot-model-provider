"""Routing helpers that translate live public model IDs into runtime metadata."""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, override, runtime_checkable

from copilot_model_provider.core.catalog import build_live_model_catalog_from_models
from copilot_model_provider.core.errors import ProviderError
from copilot_model_provider.core.models import (
    OpenAIModelCard,
    OpenAIModelListResponse,
    ResolvedRoute,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from copilot_model_provider.core.catalog import ModelCatalog
    from copilot_model_provider.runtimes.protocols import RuntimeProtocol

DEFAULT_MODEL_CATALOG_TTL_SECONDS = 30.0
DEFAULT_AUTH_CONTEXT_CACHE_KEY = '<default-auth-context>'


@dataclass(frozen=True)
class _CatalogCacheEntry:
    """One cached live-model catalog snapshot for a specific auth context.

    Attributes:
        catalog: Snapshot built from the runtime-visible model ids.
        expires_at: Monotonic clock deadline after which the snapshot is stale.

    """

    catalog: ModelCatalog
    expires_at: float


@runtime_checkable
class ModelRouterProtocol(Protocol):
    """Protocol contract for live public-model listing and resolution."""

    async def list_models_response(
        self,
        *,
        runtime_auth_token: str | None = None,
    ) -> OpenAIModelListResponse:
        """Build the public model-list response for one auth context."""
        ...

    async def resolve_model(
        self,
        *,
        model_id: str,
        runtime_auth_token: str | None = None,
    ) -> ResolvedRoute:
        """Resolve one public model identifier into runtime routing metadata."""
        ...


class ModelRouter(ModelRouterProtocol):
    """Resolve live public model IDs into runtime routing metadata."""

    def __init__(
        self,
        *,
        runtime: RuntimeProtocol,
        owned_by: str,
        catalog_ttl_seconds: float = DEFAULT_MODEL_CATALOG_TTL_SECONDS,
        time_factory: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create a router that derives its public surface from one runtime.

        Args:
            runtime: Runtime used for live model discovery and execution metadata.
            owned_by: Owner label exposed through the compatibility surface.
            catalog_ttl_seconds: Duration for which one auth-context-specific
                live-model snapshot may be reused before rediscovery.
            time_factory: Monotonic clock source used for cache expiry checks.

        """
        if catalog_ttl_seconds <= 0:
            msg = 'catalog_ttl_seconds must be positive'
            raise ValueError(msg)

        self._runtime = runtime
        self._owned_by = owned_by
        self._catalog_ttl_seconds = catalog_ttl_seconds
        self._time_factory = time_factory
        self._catalog_cache: dict[str, _CatalogCacheEntry] = {}
        self._catalog_build_locks: dict[str, asyncio.Lock] = {}

    @override
    async def list_models_response(
        self,
        *,
        runtime_auth_token: str | None = None,
    ) -> OpenAIModelListResponse:
        """Build the OpenAI-compatible model listing response.

        Returns:
            An ``OpenAIModelListResponse`` containing one card per live model ID
            visible to the supplied auth context, preserving runtime ordering and
            including optional runtime-sourced Copilot metadata when available.

        """
        model_catalog = await self._build_model_catalog(
            runtime_auth_token=runtime_auth_token
        )
        return OpenAIModelListResponse(
            data=[
                OpenAIModelCard(
                    id=entry.alias,
                    created=entry.created,
                    owned_by=entry.owned_by,
                    copilot=entry.copilot,
                )
                for entry in model_catalog.list_entries()
            ]
        )

    @override
    async def resolve_model(
        self,
        *,
        model_id: str,
        runtime_auth_token: str | None = None,
    ) -> ResolvedRoute:
        """Resolve a public model identifier into runtime routing metadata.

        Args:
            model_id: The public model identifier requested by a client.
            runtime_auth_token: Optional auth token used to discover the live
                model set that should be used for validation.

        Returns:
            A ``ResolvedRoute`` describing which runtime and runtime model ID
            should handle requests for the supplied model identifier.

        Raises:
            ProviderError: If the model identifier is not visible to the current
                auth context.

        """
        model_catalog = await self._build_model_catalog(
            runtime_auth_token=runtime_auth_token
        )
        entry = model_catalog.get_entry(alias=model_id)
        if entry is None:
            msg = f'Unknown model: {model_id!r}'
            raise ProviderError(
                code='model_not_found',
                message=msg,
                status_code=404,
            )

        return ResolvedRoute(
            runtime=entry.runtime,
            runtime_model_id=entry.runtime_model_id,
        )

    async def _build_model_catalog(
        self,
        *,
        runtime_auth_token: str | None,
    ) -> ModelCatalog:
        """Build or reuse one auth-context-specific catalog snapshot."""
        cache_key = self._build_cache_key(runtime_auth_token)
        now = self._time_factory()
        self._prune_expired_cache(now)
        cached_entry = self._catalog_cache.get(cache_key)
        if cached_entry is not None and cached_entry.expires_at > now:
            return cached_entry.catalog

        build_lock = self._catalog_build_locks.setdefault(cache_key, asyncio.Lock())
        async with build_lock:
            now = self._time_factory()
            self._prune_expired_cache(now)
            cached_entry = self._catalog_cache.get(cache_key)
            if cached_entry is not None and cached_entry.expires_at > now:
                return cached_entry.catalog

            models = await self._runtime.list_models(
                runtime_auth_token=runtime_auth_token
            )
            catalog = build_live_model_catalog_from_models(
                runtime=self._runtime.runtime_name,
                owned_by=self._owned_by,
                models=models,
            )
            self._catalog_cache[cache_key] = _CatalogCacheEntry(
                catalog=catalog,
                expires_at=self._time_factory() + self._catalog_ttl_seconds,
            )
            return catalog

    def _build_cache_key(self, runtime_auth_token: str | None) -> str:
        """Return a stable cache key for one auth context without storing raw tokens."""
        if runtime_auth_token is None:
            return DEFAULT_AUTH_CONTEXT_CACHE_KEY

        token_digest = hashlib.sha256(runtime_auth_token.encode('utf-8')).hexdigest()
        return f'token:{token_digest}'

    def _prune_expired_cache(self, now: float) -> None:
        """Drop expired cached catalogs before servicing a new lookup."""
        expired_keys = [
            key for key, entry in self._catalog_cache.items() if entry.expires_at <= now
        ]
        for key in expired_keys:
            self._catalog_cache.pop(key, None)
