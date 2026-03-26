"""Helpers for integration-style scaffold checks."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from copilot_model_provider.app import create_app
from copilot_model_provider.config import ProviderSettings

if TYPE_CHECKING:
    from fastapi import FastAPI

    from copilot_model_provider.core.routing import ModelRouterProtocol
    from copilot_model_provider.runtimes.protocols import RuntimeProtocol


def build_test_app(
    *,
    settings: ProviderSettings | None = None,
    runtime: RuntimeProtocol | None = None,
    model_router: ModelRouterProtocol | None = None,
) -> FastAPI:
    """Build the scaffold app with test-friendly defaults.

    Args:
        settings: Optional settings override for specialized test scenarios.
        runtime: Optional runtime override so tests can inject
            deterministic execution behavior.
        model_router: Optional model router override when tests need explicit routing.

    Returns:
        A FastAPI app configured the same way production code builds it, but
        defaulting the environment to ``test`` when no settings are provided.

    """
    resolved_settings = settings or ProviderSettings(environment='test')
    return create_app(
        settings=resolved_settings,
        runtime=runtime,
        model_router=model_router,
    )


def build_async_client(
    *,
    settings: ProviderSettings | None = None,
    runtime: RuntimeProtocol | None = None,
    model_router: ModelRouterProtocol | None = None,
) -> httpx.AsyncClient:
    """Build an async HTTP client bound directly to the in-process ASGI app.

    Args:
        settings: Optional settings override for the app under test.
        runtime: Optional runtime override for deterministic
            chat execution.
        model_router: Optional model router override when tests need explicit routing.

    Returns:
        An ``httpx.AsyncClient`` configured with an ``ASGITransport`` so tests
        can exercise HTTP routes without starting an external server.

    """
    app = build_test_app(
        settings=settings,
        runtime=runtime,
        model_router=model_router,
    )
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url='http://testserver')
