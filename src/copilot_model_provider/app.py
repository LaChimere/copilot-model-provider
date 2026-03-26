"""FastAPI application scaffold for the provider service."""

from __future__ import annotations

import structlog
from fastapi import FastAPI

from .api.openai_chat import install_openai_chat_route
from .api.openai_models import install_openai_models_route
from .api.openai_responses import install_openai_responses_route
from .config import ProviderSettings
from .core.catalog import ModelCatalog, create_default_model_catalog
from .core.errors import install_error_handlers
from .core.models import InternalHealthResponse
from .core.routing import ModelRouter, ModelRouterProtocol
from .runtimes import CopilotRuntime
from .runtimes.protocols import RuntimeProtocol

_logger = structlog.get_logger(__name__)


def create_app(
    settings: ProviderSettings | None = None,
    *,
    runtime: RuntimeProtocol | None = None,
    model_catalog: ModelCatalog | None = None,
    model_router: ModelRouterProtocol | None = None,
) -> FastAPI:
    """Create the provider's FastAPI application scaffold.

    When callers do not provide explicit settings or a runtime, this function
    resolves environment-backed defaults and installs the Copilot runtime for
    the thin stateless provider. The returned app exposes
    model listing plus OpenAI-compatible chat and Responses routes.

    Args:
        settings: Optional pre-built settings to bind onto the application.
        runtime: Optional runtime to store in application state.
        model_catalog: Optional pre-built service-owned model catalog.
        model_router: Optional router for model listing and alias resolution.

    Returns:
        A configured ``FastAPI`` instance ready to serve the thin provider.

    """
    resolved_settings = settings or ProviderSettings.from_env()
    resolved_runtime = _require_runtime(
        runtime
        or CopilotRuntime(
            timeout_seconds=resolved_settings.runtime_timeout_seconds,
            working_directory=resolved_settings.runtime_working_directory,
        )
    )
    resolved_router = _require_model_router(
        model_router
        or ModelRouter(
            model_catalog=model_catalog
            or create_default_model_catalog(settings=resolved_settings)
        )
    )
    resolved_catalog = resolved_router.model_catalog

    app = FastAPI(
        title=resolved_settings.app_name,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = resolved_settings
    app.state.runtime = resolved_runtime
    app.state.model_catalog = resolved_catalog
    app.state.model_router = resolved_router

    install_error_handlers(app)
    install_openai_models_route(app, model_router=resolved_router)
    install_openai_chat_route(
        app,
        model_router=resolved_router,
        runtime=resolved_runtime,
    )
    install_openai_responses_route(
        app,
        model_router=resolved_router,
        runtime=resolved_runtime,
    )

    if resolved_settings.enable_internal_health:
        _install_internal_health_route(
            app,
            settings=resolved_settings,
            runtime=resolved_runtime,
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
    runtime: RuntimeProtocol,
) -> None:
    """Install the internal-only health endpoint."""

    async def _internal_health() -> InternalHealthResponse:
        """Return the scaffold app's internal health response."""
        runtime_health = await runtime.check_health()
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


def _require_runtime(runtime: object) -> RuntimeProtocol:
    """Validate that an injected runtime dependency satisfies the runtime protocol.

    Args:
        runtime: Runtime dependency selected for application composition.

    Raises:
        TypeError: If the injected object does not satisfy the ``RuntimeProtocol``
            protocol expected by the provider.

    """
    if not isinstance(runtime, RuntimeProtocol):
        msg = 'runtime must satisfy the RuntimeProtocol protocol.'
        raise TypeError(msg)
    return runtime


def _require_model_router(model_router: object) -> ModelRouterProtocol:
    """Validate that an injected router dependency satisfies the routing protocol.

    Args:
        model_router: Router dependency selected for application composition.

    Raises:
        TypeError: If the injected object does not satisfy the
            ``ModelRouterProtocol`` protocol expected by the provider.

    """
    if not isinstance(model_router, ModelRouterProtocol):
        msg = 'model_router must satisfy the ModelRouterProtocol protocol.'
        raise TypeError(msg)
    return model_router


app = create_app()
