"""Unit tests for application bootstrapping."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from copilot_model_provider.app import create_app
from copilot_model_provider.config import ProviderSettings
from copilot_model_provider.core.catalog import (
    ModelCatalog,
    create_default_model_catalog,
)
from copilot_model_provider.core.models import ModelCatalogEntry
from copilot_model_provider.core.policies import PolicyEngine
from copilot_model_provider.core.routing import ModelRouter
from copilot_model_provider.runtimes import CopilotRuntimeAdapter
from copilot_model_provider.storage import (
    FileBackedSessionLockManager,
    FileBackedSessionMap,
)
from copilot_model_provider.tools import (
    MCPRegistry,
    MCPServerDefinition,
    ToolDefinition,
    ToolRegistry,
)
from tests.harness import build_test_app
from tests.session_persistence_helpers import managed_scratch_directory

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


def test_create_app_passes_runtime_cli_url_into_default_runtime_adapter() -> None:
    """Verify that app wiring preserves external headless CLI configuration."""
    app = create_app(
        settings=ProviderSettings(
            environment='test',
            runtime_cli_url='http://copilot-cli.internal:3000',
        )
    )

    runtime_adapter = app.state.runtime_adapter

    assert isinstance(runtime_adapter, CopilotRuntimeAdapter)
    assert runtime_adapter.connection_mode == 'external_server'
    assert runtime_adapter.external_cli_url == 'http://copilot-cli.internal:3000'


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
    """Verify that the integration harness defaults the app to the test environment."""
    app = build_test_app()

    assert isinstance(app, FastAPI)
    assert app.state.settings.environment == 'test'
    assert isinstance(app.state.tool_registry, ToolRegistry)
    assert isinstance(app.state.policy_engine, PolicyEngine)


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


def test_create_app_preserves_injected_session_primitives_for_sessional_routes() -> (
    None
):
    """Verify that session-backed routes keep the injected storage primitives."""
    model_catalog = ModelCatalog(
        entries=(
            ModelCatalogEntry(
                alias='default',
                runtime='copilot',
                owned_by='test',
                runtime_model_id='copilot-default',
                session_mode='sessional',
            ),
        )
    )
    with managed_scratch_directory('unit-app-session-state') as scratch_directory:
        session_map = FileBackedSessionMap(scratch_directory / 'session-map')
        session_lock_manager = FileBackedSessionLockManager(scratch_directory / 'locks')
        app = create_app(
            settings=ProviderSettings(environment='test'),
            model_catalog=model_catalog,
            session_map=session_map,
            session_lock_manager=session_lock_manager,
        )

    assert app.state.session_map is session_map
    assert app.state.session_lock_manager is session_lock_manager


def test_create_app_preserves_injected_tool_primitives() -> None:
    """Verify that explicit tool registry and policy engine injections are preserved."""
    tool_registry = ToolRegistry(
        (
            ToolDefinition(
                name='search-docs',
                description='Search provider documentation.',
                input_schema={'type': 'object'},
            ),
        )
    )
    policy_engine = PolicyEngine(tool_registry=tool_registry)

    app = create_app(
        settings=ProviderSettings(environment='test'),
        tool_registry=tool_registry,
        policy_engine=policy_engine,
    )

    assert app.state.tool_registry is tool_registry
    assert app.state.policy_engine is policy_engine


def test_create_app_preserves_injected_mcp_registry() -> None:
    """Verify that explicit MCP registry injections are preserved on app state."""
    mcp_registry = MCPRegistry(
        (
            MCPServerDefinition(
                name='docs-api',
                transport='http',
                url='http://localhost:8123/mcp',
            ),
        )
    )

    app = create_app(
        settings=ProviderSettings(environment='test'),
        mcp_registry=mcp_registry,
    )

    assert app.state.mcp_registry is mcp_registry


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
