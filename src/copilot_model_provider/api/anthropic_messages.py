"""Anthropic-compatible Messages endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import FastAPI, Header
from fastapi.responses import StreamingResponse

from copilot_model_provider.api.anthropic_protocol import (
    build_anthropic_content_block_delta_event,
    build_anthropic_content_block_start_event,
    build_anthropic_content_block_stop_event,
    build_anthropic_count_tokens_response,
    build_anthropic_message_delta_event,
    build_anthropic_message_id,
    build_anthropic_message_response_from_completion,
    build_anthropic_message_start_event,
    build_anthropic_message_stop_event,
    normalize_anthropic_messages_request,
)
from copilot_model_provider.api.shared import (
    close_runtime_event_stream,
    iter_canonical_runtime_stream_events,
    open_runtime_event_stream,
    resolve_runtime_auth_token_from_anthropic_headers,
)
from copilot_model_provider.core.models import (
    AnthropicCountTokensResponse,
    AnthropicMessageResponse,
    AnthropicMessagesCountTokensRequest,
    AnthropicMessagesCreateRequest,
    CanonicalChatRequest,
    ResolvedRoute,
)
from copilot_model_provider.streaming.anthropic import (
    encode_anthropic_error_event,
    encode_anthropic_event,
)
from copilot_model_provider.streaming.events import (
    AssistantTextDeltaEvent,
    StreamingErrorEvent,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from copilot_model_provider.core.routing import ModelRouterProtocol
    from copilot_model_provider.runtimes.protocols import RuntimeProtocol

_AUTHORIZATION_HEADER_NAME = 'Authorization'
_API_KEY_HEADER_NAME = 'X-Api-Key'


def install_anthropic_messages_route(
    app: FastAPI,
    *,
    default_runtime_auth_token: str | None = None,
    model_router: ModelRouterProtocol,
    runtime: RuntimeProtocol,
    path: str = '/anthropic/v1/messages',
) -> None:
    """Install the Anthropic-compatible ``POST /anthropic/v1/messages`` route.

    Args:
        app: Application instance that should serve the Messages endpoint.
        default_runtime_auth_token: Optional configured fallback auth token used
            when the request omits both ``Authorization`` and ``X-Api-Key``.
        model_router: Router that validates visible models for the auth context.
        runtime: Runtime implementation that executes the normalized request.
        path: Public HTTP path where the Anthropic facade should be installed.

    """

    async def _create_message(
        request: AnthropicMessagesCreateRequest,
        authorization_header: Annotated[
            str | None,
            Header(alias=_AUTHORIZATION_HEADER_NAME),
        ] = None,
        api_key_header: Annotated[
            str | None,
            Header(alias=_API_KEY_HEADER_NAME),
        ] = None,
    ) -> AnthropicMessageResponse | StreamingResponse:
        """Execute an Anthropic Messages request through the existing runtime."""
        runtime_auth_token = resolve_runtime_auth_token_from_anthropic_headers(
            authorization_header=authorization_header,
            api_key_header=api_key_header,
            default_token=default_runtime_auth_token,
        )
        route = await model_router.resolve_model(
            model_id=request.model,
            runtime_auth_token=runtime_auth_token,
        )
        canonical_request = normalize_anthropic_messages_request(
            request=request,
            runtime_auth_token=runtime_auth_token,
        )
        if request.stream:
            return await _create_streaming_message(
                request=request,
                runtime=runtime,
                route=route,
                canonical_request=canonical_request,
            )

        completion = await runtime.complete_chat(
            request=canonical_request,
            route=route,
        )
        return build_anthropic_message_response_from_completion(
            request=request,
            completion=completion,
            message_id=build_anthropic_message_id(),
        )

    app.add_api_route(
        path,
        _create_message,
        methods=['POST'],
        response_model=AnthropicMessageResponse,
    )


def install_anthropic_count_tokens_route(
    app: FastAPI,
    *,
    default_runtime_auth_token: str | None = None,
    model_router: ModelRouterProtocol,
    path: str = '/anthropic/v1/messages/count_tokens',
) -> None:
    """Install the Anthropic-compatible ``POST /v1/messages/count_tokens`` route."""

    async def _count_tokens(
        request: AnthropicMessagesCountTokensRequest,
        authorization_header: Annotated[
            str | None,
            Header(alias=_AUTHORIZATION_HEADER_NAME),
        ] = None,
        api_key_header: Annotated[
            str | None,
            Header(alias=_API_KEY_HEADER_NAME),
        ] = None,
    ) -> AnthropicCountTokensResponse:
        """Return a best-effort Anthropic-compatible input-token count."""
        runtime_auth_token = resolve_runtime_auth_token_from_anthropic_headers(
            authorization_header=authorization_header,
            api_key_header=api_key_header,
            default_token=default_runtime_auth_token,
        )
        await model_router.resolve_model(
            model_id=request.model,
            runtime_auth_token=runtime_auth_token,
        )
        return build_anthropic_count_tokens_response(request=request)

    app.add_api_route(
        path,
        _count_tokens,
        methods=['POST'],
        response_model=AnthropicCountTokensResponse,
    )


async def _create_streaming_message(
    *,
    request: AnthropicMessagesCreateRequest,
    runtime: RuntimeProtocol,
    route: ResolvedRoute,
    canonical_request: CanonicalChatRequest,
) -> StreamingResponse:
    """Create a streaming Anthropic-compatible SSE response."""
    runtime_stream = None
    try:
        runtime_stream = await open_runtime_event_stream(
            runtime=runtime,
            request=canonical_request,
            route=route,
        )
        message_id = build_anthropic_message_id()
    except Exception:
        if runtime_stream is not None:
            await close_runtime_event_stream(runtime_stream=runtime_stream)
        raise

    async def _frame_stream() -> AsyncIterator[str]:
        """Yield Anthropic-compatible SSE frames for one streamed message."""
        yield encode_anthropic_event(
            event='message_start',
            payload=build_anthropic_message_start_event(
                model=request.model,
                message_id=message_id,
            ).model_dump_json(exclude_none=True),
        )
        yield encode_anthropic_event(
            event='content_block_start',
            payload=build_anthropic_content_block_start_event().model_dump_json(
                exclude_none=True
            ),
        )
        async for stream_event in iter_canonical_runtime_stream_events(
            runtime_stream=runtime_stream
        ):
            if isinstance(stream_event, StreamingErrorEvent):
                yield encode_anthropic_error_event(message=stream_event.message)
                return

            if isinstance(stream_event, AssistantTextDeltaEvent):
                yield encode_anthropic_event(
                    event='content_block_delta',
                    payload=build_anthropic_content_block_delta_event(
                        text=stream_event.text
                    ).model_dump_json(exclude_none=True),
                )
                continue

            yield encode_anthropic_event(
                event='content_block_stop',
                payload=build_anthropic_content_block_stop_event().model_dump_json(
                    exclude_none=True
                ),
            )
            yield encode_anthropic_event(
                event='message_delta',
                payload=build_anthropic_message_delta_event(
                    stop_reason=stream_event.finish_reason
                ).model_dump_json(exclude_none=True),
            )
            yield encode_anthropic_event(
                event='message_stop',
                payload=build_anthropic_message_stop_event().model_dump_json(
                    exclude_none=True
                ),
            )
            return

    return StreamingResponse(_frame_stream(), media_type='text/event-stream')
