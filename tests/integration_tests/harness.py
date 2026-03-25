"""Helpers for integration-style scaffold checks."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from copilot_model_provider.app import create_app
from copilot_model_provider.config import ProviderSettings

if TYPE_CHECKING:
    from fastapi import FastAPI

    from copilot_model_provider.core.catalog import ModelCatalog
    from copilot_model_provider.core.policies import PolicyEngine
    from copilot_model_provider.core.routing import ModelRouter
    from copilot_model_provider.runtimes.base import RuntimeAdapter
    from copilot_model_provider.storage import SessionLockManager, SessionMap
    from copilot_model_provider.tools import MCPRegistry, ToolRegistry


def build_test_app(
    *,
    settings: ProviderSettings | None = None,
    runtime_adapter: RuntimeAdapter | None = None,
    model_catalog: ModelCatalog | None = None,
    model_router: ModelRouter | None = None,
    session_map: SessionMap | None = None,
    session_lock_manager: SessionLockManager | None = None,
    tool_registry: ToolRegistry | None = None,
    policy_engine: PolicyEngine | None = None,
    mcp_registry: MCPRegistry | None = None,
) -> FastAPI:
    """Build the scaffold app with test-friendly defaults.

    Args:
        settings: Optional settings override for specialized test scenarios.
        runtime_adapter: Optional runtime adapter override so tests can inject
            deterministic execution behavior.
        model_catalog: Optional model catalog override for route/session-mode tests.
        model_router: Optional model router override when tests need explicit routing.
        session_map: Optional injected session map used by session-backed tests.
        session_lock_manager: Optional injected session lock manager used by
            session-backed tests.
        tool_registry: Optional injected tool registry used by runtime permission
            and future Tool/MCP tests.
        policy_engine: Optional injected policy engine used by runtime permission
            and future Tool/MCP tests.
        mcp_registry: Optional injected MCP registry used by later Step 4
            session-mount and integration tests.

    Returns:
        A FastAPI app configured the same way production code builds it, but
        defaulting the environment to ``test`` when no settings are provided.

    """
    resolved_settings = settings or ProviderSettings(environment='test')
    return create_app(
        settings=resolved_settings,
        runtime_adapter=runtime_adapter,
        model_catalog=model_catalog,
        model_router=model_router,
        session_map=session_map,
        session_lock_manager=session_lock_manager,
        tool_registry=tool_registry,
        policy_engine=policy_engine,
        mcp_registry=mcp_registry,
    )


def build_async_client(
    *,
    settings: ProviderSettings | None = None,
    runtime_adapter: RuntimeAdapter | None = None,
    model_catalog: ModelCatalog | None = None,
    model_router: ModelRouter | None = None,
    session_map: SessionMap | None = None,
    session_lock_manager: SessionLockManager | None = None,
    tool_registry: ToolRegistry | None = None,
    policy_engine: PolicyEngine | None = None,
    mcp_registry: MCPRegistry | None = None,
) -> httpx.AsyncClient:
    """Build an async HTTP client bound directly to the in-process ASGI app.

    Args:
        settings: Optional settings override for the app under test.
        runtime_adapter: Optional runtime adapter override for deterministic
            chat execution.
        model_catalog: Optional model catalog override for route/session-mode tests.
        model_router: Optional model router override when tests need explicit routing.
        session_map: Optional injected session map used by session-backed tests.
        session_lock_manager: Optional injected session lock manager used by
            session-backed tests.
        tool_registry: Optional injected tool registry used by runtime permission
            and future Tool/MCP tests.
        policy_engine: Optional injected policy engine used by runtime permission
            and future Tool/MCP tests.
        mcp_registry: Optional injected MCP registry used by later Step 4
            session-mount and integration tests.

    Returns:
        An ``httpx.AsyncClient`` configured with an ``ASGITransport`` so tests
        can exercise HTTP routes without starting an external server.

    """
    app = build_test_app(
        settings=settings,
        runtime_adapter=runtime_adapter,
        model_catalog=model_catalog,
        model_router=model_router,
        session_map=session_map,
        session_lock_manager=session_lock_manager,
        tool_registry=tool_registry,
        policy_engine=policy_engine,
        mcp_registry=mcp_registry,
    )
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url='http://testserver')
