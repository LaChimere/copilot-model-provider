"""OpenAI-compatible model catalog endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

from copilot_model_provider.core.models import OpenAIModelListResponse

if TYPE_CHECKING:
    from fastapi import FastAPI

    from copilot_model_provider.core.routing import ModelRouter


def install_openai_models_route(app: FastAPI, *, model_router: ModelRouter) -> None:
    """Install the OpenAI-compatible ``GET /v1/models`` route.

    Args:
        app: The application instance that should serve the models endpoint.
        model_router: The router that owns the stable public aliases and their
            read-only response representation.

    """

    async def _list_models() -> OpenAIModelListResponse:
        """Return the service-owned OpenAI-compatible model list."""
        return model_router.list_models_response()

    app.add_api_route(
        '/v1/models',
        _list_models,
        methods=['GET'],
        response_model=OpenAIModelListResponse,
    )
