"""Unit tests for live model-catalog snapshots and routing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import override

import pytest

from copilot_model_provider.core.catalog import (
    ModelCatalog,
    build_live_model_catalog,
    build_live_model_catalog_from_models,
)
from copilot_model_provider.core.errors import ProviderError
from copilot_model_provider.core.models import (
    CopilotModelMetadata,
    ModelCatalogEntry,
    ResolvedRoute,
    RuntimeCompletion,
    RuntimeDiscoveredModel,
    RuntimeHealth,
)
from copilot_model_provider.core.routing import ModelRouter
from copilot_model_provider.runtimes.protocols import (
    RuntimeEventStream,
    RuntimeProtocol,
)


class _FakeRuntime(RuntimeProtocol):
    """Minimal runtime used to drive auth-aware router tests."""

    def __init__(
        self,
        *,
        model_ids_by_token: dict[str | None, tuple[str, ...]] | None = None,
    ) -> None:
        """Initialize the fake runtime state."""
        self.tokens_seen: list[str | None] = []
        self._model_ids_by_token = model_ids_by_token or {
            None: ('gpt-5.4', 'gpt-5.4-mini'),
        }

    @property
    @override
    def runtime_name(self) -> str:
        """Return the fake runtime name."""
        return 'copilot'

    @override
    def default_route(self) -> ResolvedRoute:
        """Return the fake default route."""
        return ResolvedRoute(runtime='copilot')

    @override
    async def check_health(self) -> RuntimeHealth:
        """Return a healthy fake runtime payload."""
        return RuntimeHealth(runtime='copilot', available=True, detail='ok')

    @override
    async def list_model_ids(
        self,
        *,
        runtime_auth_token: str | None = None,
    ) -> tuple[str, ...]:
        """Return a deterministic live-model list while recording auth context."""
        self.tokens_seen.append(runtime_auth_token)
        return self._model_ids_by_token.get(
            runtime_auth_token,
            self._model_ids_by_token.get(None, ('gpt-5.4', 'gpt-5.4-mini')),
        )

    @override
    async def complete_chat(self, **kwargs: object) -> RuntimeCompletion:
        """Reject unexpected execution calls in router-only tests."""
        del kwargs
        raise AssertionError('complete_chat should not be called in this test')

    @override
    async def stream_chat(self, **kwargs: object) -> RuntimeEventStream:
        """Reject unexpected streaming calls in router-only tests."""
        del kwargs
        raise AssertionError('stream_chat should not be called in this test')


@dataclass
class _FakeClock:
    """Controllable monotonic clock used to verify cache expiry behavior."""

    current_time: float = 100.0

    def __call__(self) -> float:
        """Return the current fake monotonic time."""
        return self.current_time

    def advance(self, seconds: float) -> None:
        """Advance the fake monotonic clock by the requested duration."""
        self.current_time += seconds


def test_live_catalog_exposes_same_name_public_model_ids() -> None:
    """Verify that a live model snapshot preserves runtime model IDs verbatim."""
    catalog = build_live_model_catalog(
        runtime='copilot',
        owned_by='catalog-test',
        model_ids=['gpt-5.4', 'gpt-5.4-mini'],
    )

    assert [entry.alias for entry in catalog.list_entries()] == [
        'gpt-5.4',
        'gpt-5.4-mini',
    ]
    assert [entry.owned_by for entry in catalog.list_entries()] == [
        'catalog-test',
        'catalog-test',
    ]


def test_live_catalog_from_models_preserves_copilot_metadata() -> None:
    """Verify metadata-aware catalog building preserves provider-owned metadata."""
    catalog = build_live_model_catalog_from_models(
        runtime='copilot',
        owned_by='catalog-test',
        models=[
            RuntimeDiscoveredModel(
                id='claude-opus-4.6-1m',
                copilot=CopilotModelMetadata(
                    name='Claude Opus 4.6 (1M context)(Internal only)'
                ),
            )
        ],
    )

    entry = catalog.get_entry(alias='claude-opus-4.6-1m')

    assert entry is not None
    assert entry.copilot is not None
    assert entry.copilot.name == 'Claude Opus 4.6 (1M context)(Internal only)'


def test_catalog_rejects_duplicate_aliases() -> None:
    """Verify that the catalog refuses ambiguous duplicate public aliases."""
    entry = ModelCatalogEntry(
        alias='gpt-5.4',
        runtime='copilot',
        owned_by='catalog-test',
        runtime_model_id='gpt-5.4',
    )

    with pytest.raises(ValueError, match='aliases must be unique'):
        ModelCatalog(entries=(entry, entry))


@pytest.mark.asyncio
async def test_runtime_protocol_list_models_shim_wraps_live_ids() -> None:
    """Verify the additive discovery shim preserves legacy fake-runtime behavior."""
    runtime = _FakeRuntime()

    models = await runtime.list_models()

    assert [model.id for model in models] == ['gpt-5.4', 'gpt-5.4-mini']
    assert runtime.tokens_seen == [None]


@pytest.mark.asyncio
async def test_router_lists_openai_compatible_model_cards() -> None:
    """Verify that the router converts live runtime IDs into OpenAI model cards."""
    router = ModelRouter(runtime=_FakeRuntime(), owned_by='catalog-test')

    response = await router.list_models_response()

    assert response.object == 'list'
    assert [item.id for item in response.data] == ['gpt-5.4', 'gpt-5.4-mini']
    assert all(item.object == 'model' for item in response.data)


@pytest.mark.asyncio
async def test_router_resolves_known_model_id_into_runtime_route() -> None:
    """Verify that a known live model ID resolves into runtime metadata."""
    runtime = _FakeRuntime()
    router = ModelRouter(runtime=runtime, owned_by='catalog-test')

    route = await router.resolve_model(
        model_id='gpt-5.4-mini',
        runtime_auth_token='github-token-123',  # noqa: S106 - deterministic test token
    )

    assert route.runtime == 'copilot'
    assert route.runtime_model_id == 'gpt-5.4-mini'
    assert runtime.tokens_seen == ['github-token-123']


@pytest.mark.asyncio
async def test_router_raises_provider_error_for_unknown_model_id() -> None:
    """Verify that unknown model IDs fail with a structured provider error."""
    router = ModelRouter(runtime=_FakeRuntime(), owned_by='catalog-test')

    with pytest.raises(ProviderError, match='Unknown model'):
        await router.resolve_model(model_id='missing')


@pytest.mark.asyncio
async def test_router_reuses_cached_catalog_within_ttl_for_same_auth_context() -> None:
    """Verify repeated lookups reuse one cached live-model snapshot within its TTL."""
    runtime = _FakeRuntime()
    clock = _FakeClock()
    router = ModelRouter(
        runtime=runtime,
        owned_by='catalog-test',
        catalog_ttl_seconds=30.0,
        time_factory=clock,
    )

    first_route = await router.resolve_model(
        model_id='gpt-5.4',
        runtime_auth_token='github-token-123',  # noqa: S106 - deterministic test token
    )
    second_route = await router.resolve_model(
        model_id='gpt-5.4-mini',
        runtime_auth_token='github-token-123',  # noqa: S106 - deterministic test token
    )

    assert first_route.runtime_model_id == 'gpt-5.4'
    assert second_route.runtime_model_id == 'gpt-5.4-mini'
    assert runtime.tokens_seen == ['github-token-123']


@pytest.mark.asyncio
async def test_router_refreshes_cached_catalog_after_ttl_expiry() -> None:
    """Verify expired live-model snapshots are rediscovered on the next lookup."""
    runtime = _FakeRuntime()
    clock = _FakeClock()
    router = ModelRouter(
        runtime=runtime,
        owned_by='catalog-test',
        catalog_ttl_seconds=5.0,
        time_factory=clock,
    )

    await router.list_models_response()
    clock.advance(6.0)
    await router.list_models_response()

    assert runtime.tokens_seen == [None, None]


@pytest.mark.asyncio
async def test_router_keeps_auth_context_caches_isolated() -> None:
    """Verify distinct auth contexts do not reuse each other's cached model sets."""
    runtime = _FakeRuntime(
        model_ids_by_token={
            None: ('gpt-5.4',),
            'token-a': ('gpt-5.4', 'gpt-5.4-mini'),
            'token-b': ('claude-sonnet-4.6',),
        }
    )
    clock = _FakeClock()
    router = ModelRouter(
        runtime=runtime,
        owned_by='catalog-test',
        catalog_ttl_seconds=30.0,
        time_factory=clock,
    )

    token_a_response = await router.list_models_response(
        runtime_auth_token='token-a',  # noqa: S106 - deterministic test token
    )
    token_b_response = await router.list_models_response(
        runtime_auth_token='token-b',  # noqa: S106 - deterministic test token
    )
    token_a_repeat = await router.list_models_response(
        runtime_auth_token='token-a',  # noqa: S106 - deterministic test token
    )

    assert [item.id for item in token_a_response.data] == ['gpt-5.4', 'gpt-5.4-mini']
    assert [item.id for item in token_b_response.data] == ['claude-sonnet-4.6']
    assert [item.id for item in token_a_repeat.data] == ['gpt-5.4', 'gpt-5.4-mini']
    assert runtime.tokens_seen == ['token-a', 'token-b']
