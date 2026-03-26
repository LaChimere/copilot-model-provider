"""OpenAI-compatible model catalog endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Header

from copilot_model_provider.api.shared import resolve_runtime_auth_token
from copilot_model_provider.core.models import OpenAIModelListResponse

if TYPE_CHECKING:
    from fastapi import FastAPI

    from copilot_model_provider.core.routing import ModelRouterProtocol


def install_openai_models_route(
    app: FastAPI,
    *,
    default_runtime_auth_token: str | None = None,
    model_router: ModelRouterProtocol,
) -> None:
    """Install the OpenAI-compatible ``GET /v1/models`` route.

    Args:
        app: The application instance that should serve the models endpoint.
        default_runtime_auth_token: Optional configured fallback auth token used
            when the request omits ``Authorization``.
        model_router: The router that resolves live model visibility for the
            active auth context.

    """

    async def _list_models(
        authorization_header: Annotated[
            str | None,
            Header(alias='Authorization'),
        ] = None,
    ) -> OpenAIModelListResponse:
        """Return the auth-context-aware OpenAI-compatible model list."""
        runtime_auth_token = resolve_runtime_auth_token(
            authorization_header=authorization_header,
            default_token=default_runtime_auth_token,
        )
        return await model_router.list_models_response(
            runtime_auth_token=runtime_auth_token
        )

    app.add_api_route(
        '/v1/models',
        _list_models,
        methods=['GET'],
        response_model=OpenAIModelListResponse,
    )
