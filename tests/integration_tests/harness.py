"""Helpers for integration-style scaffold checks."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from copilot_model_provider.app import create_app
from copilot_model_provider.config import ProviderSettings

if TYPE_CHECKING:
    from fastapi import FastAPI


def build_test_app(*, settings: ProviderSettings | None = None) -> FastAPI:
    """Build the scaffold app with test-friendly defaults.

    Args:
        settings: Optional settings override for specialized test scenarios.

    Returns:
        A FastAPI app configured the same way production code builds it, but
        defaulting the environment to ``test`` when no settings are provided.

    """
    resolved_settings = settings or ProviderSettings(environment='test')
    return create_app(settings=resolved_settings)


def build_async_client(
    *, settings: ProviderSettings | None = None
) -> httpx.AsyncClient:
    """Build an async HTTP client bound directly to the in-process ASGI app.

    Args:
        settings: Optional settings override for the app under test.

    Returns:
        An ``httpx.AsyncClient`` configured with an ``ASGITransport`` so tests
        can exercise HTTP routes without starting an external server.

    """
    app = build_test_app(settings=settings)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url='http://testserver')
