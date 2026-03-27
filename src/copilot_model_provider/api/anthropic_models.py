"""Anthropic-compatible model catalog endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Header

from copilot_model_provider.api.anthropic_protocol import (
    build_anthropic_model_list_response,
)
from copilot_model_provider.api.shared import (
    resolve_runtime_auth_token_from_anthropic_headers,
)
from copilot_model_provider.core.models import AnthropicModelListResponse

if TYPE_CHECKING:
    from fastapi import FastAPI

    from copilot_model_provider.core.routing import ModelRouterProtocol


def install_anthropic_models_route(
    app: FastAPI,
    *,
    default_runtime_auth_token: str | None = None,
    model_router: ModelRouterProtocol,
    path: str = '/anthropic/v1/models',
) -> None:
    """Install the Anthropic-compatible ``GET /anthropic/v1/models`` route."""

    async def _list_models(
        authorization_header: Annotated[
            str | None,
            Header(alias='Authorization'),
        ] = None,
        api_key_header: Annotated[
            str | None,
            Header(alias='X-Api-Key'),
        ] = None,
    ) -> AnthropicModelListResponse:
        """Return the auth-context-aware Anthropic-compatible model list."""
        runtime_auth_token = resolve_runtime_auth_token_from_anthropic_headers(
            authorization_header=authorization_header,
            api_key_header=api_key_header,
            default_token=default_runtime_auth_token,
        )
        openai_response = await model_router.list_models_response(
            runtime_auth_token=runtime_auth_token
        )
        return build_anthropic_model_list_response(openai_response=openai_response)

    app.add_api_route(
        path,
        _list_models,
        methods=['GET'],
        response_model=AnthropicModelListResponse,
    )
