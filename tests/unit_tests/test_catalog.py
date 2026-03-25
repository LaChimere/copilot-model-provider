"""Unit tests for the service-owned model catalog and router."""

from __future__ import annotations

import pytest

from copilot_model_provider.config import ProviderSettings
from copilot_model_provider.core.catalog import (
    ModelCatalog,
    create_default_model_catalog,
)
from copilot_model_provider.core.errors import ProviderError
from copilot_model_provider.core.models import ModelCatalogEntry
from copilot_model_provider.core.routing import ModelRouter


def test_default_catalog_exposes_stable_public_aliases() -> None:
    """Verify that the default catalog returns the expected public aliases in order."""
    settings = ProviderSettings(app_name='catalog-test', default_runtime='copilot')

    catalog = create_default_model_catalog(settings=settings)

    assert [entry.alias for entry in catalog.list_entries()] == ['default', 'fast']
    assert [entry.owned_by for entry in catalog.list_entries()] == [
        'catalog-test',
        'catalog-test',
    ]


def test_catalog_rejects_duplicate_aliases() -> None:
    """Verify that the catalog refuses ambiguous duplicate public aliases."""
    entry = ModelCatalogEntry(
        alias='default',
        runtime='copilot',
        owned_by='catalog-test',
        runtime_model_id='copilot-default',
    )

    with pytest.raises(ValueError, match='aliases must be unique'):
        ModelCatalog(entries=(entry, entry))


def test_router_lists_openai_compatible_model_cards() -> None:
    """Verify that the router converts catalog entries into OpenAI model cards."""
    router = ModelRouter(
        model_catalog=create_default_model_catalog(settings=ProviderSettings()),
    )

    response = router.list_models_response()

    assert response.object == 'list'
    assert [item.id for item in response.data] == ['default', 'fast']
    assert all(item.object == 'model' for item in response.data)


def test_router_resolves_known_alias_into_runtime_route() -> None:
    """Verify that a known alias resolves into runtime metadata for later execution."""
    router = ModelRouter(
        model_catalog=create_default_model_catalog(settings=ProviderSettings()),
    )

    route = router.resolve_model(alias='fast')

    assert route.runtime == 'copilot'
    assert route.session_mode == 'stateless'
    assert route.runtime_model_id == 'copilot-fast'


def test_router_raises_provider_error_for_unknown_alias() -> None:
    """Verify that unknown aliases fail with a structured provider error."""
    router = ModelRouter(
        model_catalog=create_default_model_catalog(settings=ProviderSettings()),
    )

    with pytest.raises(ProviderError, match='Unknown model alias'):
        router.resolve_model(alias='missing')
