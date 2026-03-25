"""FastAPI application scaffold for the provider service."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from fastapi import FastAPI

from .api.openai_chat import install_openai_chat_route
from .api.openai_models import install_openai_models_route
from .config import ProviderSettings
from .core.catalog import ModelCatalog, create_default_model_catalog
from .core.errors import install_error_handlers
from .core.models import InternalHealthResponse
from .core.routing import ModelRouter
from .runtimes import CopilotRuntimeAdapter
from .storage import FileBackedSessionLockManager, FileBackedSessionMap

if TYPE_CHECKING:
    from .runtimes.base import RuntimeAdapter
    from .storage import SessionLockManager, SessionMap

_logger = structlog.get_logger(__name__)


def create_app(
    settings: ProviderSettings | None = None,
    *,
    runtime_adapter: RuntimeAdapter | None = None,
    model_catalog: ModelCatalog | None = None,
    model_router: ModelRouter | None = None,
    session_map: SessionMap | None = None,
    session_lock_manager: SessionLockManager | None = None,
) -> FastAPI:
    """Create the provider's FastAPI application scaffold.

    When callers do not provide explicit settings or a runtime adapter, this
    function resolves environment-backed defaults and installs the Copilot
    runtime adapter for the first non-streaming execution slice. The returned
    app exposes the model listing route, the OpenAI-compatible chat-completions
    route, and the internal plumbing needed for later provider phases.

    Args:
        settings: Optional pre-built settings to bind onto the application.
        runtime_adapter: Optional runtime adapter to store in application state.
        model_catalog: Optional pre-built service-owned model catalog.
        model_router: Optional router for model listing and alias resolution.
        session_map: Optional session persistence backend for session-backed chat.
        session_lock_manager: Optional lock manager for session-backed chat.

    Returns:
        A configured ``FastAPI`` instance ready for later provider phases.

    """
    resolved_settings = settings or ProviderSettings.from_env()
    resolved_runtime = runtime_adapter or CopilotRuntimeAdapter(
        timeout_seconds=resolved_settings.runtime_timeout_seconds,
        working_directory=resolved_settings.runtime_working_directory,
    )
    resolved_router = model_router or ModelRouter(
        model_catalog=model_catalog
        or create_default_model_catalog(settings=resolved_settings)
    )
    resolved_catalog = resolved_router.model_catalog
    resolved_session_map = session_map
    resolved_session_lock_manager = session_lock_manager
    if _catalog_requires_session_storage(model_catalog=resolved_catalog):
        storage_root = _build_storage_root_directory(settings=resolved_settings)
        if resolved_session_map is None:
            resolved_session_map = FileBackedSessionMap(storage_root / 'session-map')
        if resolved_session_lock_manager is None:
            resolved_session_lock_manager = FileBackedSessionLockManager(
                storage_root / 'locks'
            )

    app = FastAPI(
        title=resolved_settings.app_name,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = resolved_settings
    app.state.runtime_adapter = resolved_runtime
    app.state.model_catalog = resolved_catalog
    app.state.model_router = resolved_router
    app.state.session_map = resolved_session_map
    app.state.session_lock_manager = resolved_session_lock_manager

    install_error_handlers(app)
    install_openai_models_route(app, model_router=resolved_router)
    install_openai_chat_route(
        app,
        model_router=resolved_router,
        runtime_adapter=resolved_runtime,
    )

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


def _catalog_requires_session_storage(*, model_catalog: ModelCatalog) -> bool:
    """Report whether any configured model route requires session persistence."""
    return any(
        entry.session_mode == 'sessional' for entry in model_catalog.list_entries()
    )


def _build_storage_root_directory(*, settings: ProviderSettings) -> Path:
    """Build the default local storage directory for session-backed execution."""
    working_directory = Path(settings.runtime_working_directory or '.').resolve()
    return working_directory / '.copilot-model-provider-state'


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
