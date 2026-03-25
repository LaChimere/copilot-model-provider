"""OpenAI-compatible non-streaming chat-completions endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

from copilot_model_provider.core.chat import (
    build_openai_chat_completion_response,
    normalize_openai_chat_request,
)
from copilot_model_provider.core.models import (
    OpenAIChatCompletionRequest,
    OpenAIChatCompletionResponse,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

    from copilot_model_provider.core.routing import ModelRouter
    from copilot_model_provider.runtimes.base import RuntimeAdapter


def install_openai_chat_route(
    app: FastAPI,
    *,
    model_router: ModelRouter,
    runtime_adapter: RuntimeAdapter,
) -> None:
    """Install the OpenAI-compatible ``POST /v1/chat/completions`` route.

    Args:
        app: The application instance that should serve the chat endpoint.
        model_router: The router used to resolve the public ``model`` alias.
        runtime_adapter: The backend adapter that executes the normalized chat
            request once routing is complete.

    """

    async def _create_chat_completion(
        request: OpenAIChatCompletionRequest,
    ) -> OpenAIChatCompletionResponse:
        """Execute a non-streaming chat completion through the runtime adapter."""
        canonical_request = normalize_openai_chat_request(request=request)
        route = model_router.resolve_model(alias=canonical_request.model_alias)
        completion = await runtime_adapter.complete_chat(
            request=canonical_request,
            route=route,
        )
        return build_openai_chat_completion_response(
            request=request,
            completion=completion,
        )

    app.add_api_route(
        '/v1/chat/completions',
        _create_chat_completion,
        methods=['POST'],
        response_model=OpenAIChatCompletionResponse,
    )
