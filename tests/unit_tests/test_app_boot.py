"""Unit tests for application bootstrapping."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from copilot_model_provider.app import create_app
from copilot_model_provider.config import ProviderSettings
from copilot_model_provider.core.catalog import create_default_model_catalog
from copilot_model_provider.core.routing import ModelRouter
from tests.harness import build_test_app

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from copilot_model_provider.core.models import InternalHealthResponse


def _route_paths(app: FastAPI) -> set[str]:
    """Collect registered paths from the FastAPI app."""
    return {route.path for route in app.routes if isinstance(route, APIRoute)}


def test_create_app_returns_fastapi_application() -> None:
    """Verify that ``create_app`` returns a typed FastAPI scaffold instance."""
    app = create_app(settings=ProviderSettings())

    assert isinstance(app, FastAPI)
    assert app.title == 'copilot-model-provider'
    assert app.state.model_router.list_models_response().data


def test_internal_health_route_is_optional() -> None:
    """Verify that the internal health route is gated by configuration."""
    enabled_app = create_app(
        settings=ProviderSettings(enable_internal_health=True),
    )
    disabled_app = create_app(
        settings=ProviderSettings(enable_internal_health=False),
    )

    assert '/v1/models' in _route_paths(enabled_app)
    assert '/v1/models' in _route_paths(disabled_app)
    assert '/v1/chat/completions' in _route_paths(enabled_app)
    assert '/v1/chat/completions' in _route_paths(disabled_app)
    assert '/_internal/health' in _route_paths(enabled_app)
    assert '/_internal/health' not in _route_paths(disabled_app)


def test_harness_builds_test_application() -> None:
    """Verify that the harness defaults the app to the test environment."""
    app = build_test_app()

    assert isinstance(app, FastAPI)
    assert app.state.settings.environment == 'test'
    assert app.state.model_catalog.list_entries()


def test_create_app_uses_router_catalog_when_router_is_supplied() -> None:
    """Verify that app state stays consistent when a custom router is supplied."""
    settings = ProviderSettings()
    explicit_catalog = create_default_model_catalog(settings=settings)
    router_catalog = create_default_model_catalog(
        settings=ProviderSettings(app_name='router-owned'),
    )
    router = ModelRouter(model_catalog=router_catalog)

    app = create_app(
        settings=settings,
        model_catalog=explicit_catalog,
        model_router=router,
    )

    assert app.state.model_router is router
    assert app.state.model_catalog is router_catalog
    assert app.state.model_router.model_catalog is app.state.model_catalog


@pytest.mark.asyncio
async def test_internal_health_handler_returns_scaffold_payload() -> None:
    """Verify that the internal health handler reports lazy Copilot state."""
    app = create_app(settings=ProviderSettings(environment='test'))
    endpoint = _resolve_endpoint(app, '/_internal/health')
    response: InternalHealthResponse = await endpoint()

    assert response.status == 'ok'
    assert response.service == 'copilot-model-provider'
    assert response.environment == 'test'
    assert response.runtime.runtime == 'copilot'
    assert response.runtime.available is False
    assert response.runtime.detail == 'Copilot client state: disconnected'


def _resolve_endpoint(
    app: FastAPI,
    path: str,
) -> Callable[[], Awaitable[InternalHealthResponse]]:
    """Find the callable endpoint for a registered route."""
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == path:
            return route.endpoint

    msg = f'Unable to find route for path {path!r}'
    raise AssertionError(msg)
