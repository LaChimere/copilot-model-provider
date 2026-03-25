"""FastAPI application scaffold for the provider service."""

from __future__ import annotations

import structlog
from fastapi import FastAPI

from .config import ProviderSettings
from .core.errors import install_error_handlers
from .core.models import InternalHealthResponse
from .runtimes.base import RuntimeAdapter, ScaffoldRuntimeAdapter

_logger = structlog.get_logger(__name__)


def create_app(
    settings: ProviderSettings | None = None,
    *,
    runtime_adapter: RuntimeAdapter | None = None,
) -> FastAPI:
    """Create the provider's FastAPI application scaffold.

    When callers do not provide explicit settings or a runtime adapter, this
    function resolves environment-backed defaults and installs the non-executing
    scaffold runtime. The returned app intentionally exposes only internal
    plumbing needed for PR 1, including typed state and the optional internal
    health endpoint.

    Args:
        settings: Optional pre-built settings to bind onto the application.
        runtime_adapter: Optional runtime adapter to store in application state.

    Returns:
        A configured ``FastAPI`` instance ready for later provider phases.

    """
    resolved_settings = settings or ProviderSettings.from_env()
    resolved_runtime = runtime_adapter or ScaffoldRuntimeAdapter()

    app = FastAPI(
        title=resolved_settings.app_name,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = resolved_settings
    app.state.runtime_adapter = resolved_runtime

    install_error_handlers(app)

    if resolved_settings.enable_internal_health:
        _install_internal_health_route(
            app,
            settings=resolved_settings,
            runtime_adapter=resolved_runtime,
        )

    _logger.info(
        'app_created',
        app_name=resolved_settings.app_name,
        environment=resolved_settings.environment,
        internal_health=resolved_settings.enable_internal_health,
        runtime=resolved_runtime.runtime_name,
    )
    return app


def _install_internal_health_route(
    app: FastAPI,
    *,
    settings: ProviderSettings,
    runtime_adapter: RuntimeAdapter,
) -> None:
    """Install the internal-only health endpoint."""

    async def _internal_health() -> InternalHealthResponse:
        """Return the scaffold app's internal health response."""
        runtime_health = await runtime_adapter.check_health()
        return InternalHealthResponse(
            service=settings.app_name,
            environment=settings.environment,
            runtime=runtime_health,
        )

    app.add_api_route(
        settings.internal_health_path,
        _internal_health,
        include_in_schema=False,
        response_model=InternalHealthResponse,
        methods=['GET'],
    )


app = create_app()
