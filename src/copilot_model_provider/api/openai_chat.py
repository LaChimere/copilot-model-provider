"""OpenAI-compatible chat-completions endpoint."""

from __future__ import annotations

import json
from time import time
from typing import TYPE_CHECKING, Annotated
from uuid import uuid4

from fastapi import FastAPI, Header
from fastapi.responses import StreamingResponse

from copilot_model_provider.api.shared import (
    close_runtime_event_stream,
    normalize_bearer_token,
)
from copilot_model_provider.core.chat import (
    build_openai_chat_completion_response,
    normalize_openai_chat_request,
)
from copilot_model_provider.core.models import (
    CanonicalChatRequest,
    OpenAIChatCompletionRequest,
    OpenAIChatCompletionResponse,
    ResolvedRoute,
)
from copilot_model_provider.streaming.events import StreamingErrorEvent
from copilot_model_provider.streaming.sse import (
    encode_openai_chat_chunk,
    encode_openai_done_event,
    encode_sse_event,
)
from copilot_model_provider.streaming.translators import (
    translate_session_event,
    translate_stream_event_to_openai_chunks,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from copilot_model_provider.core.routing import ModelRouter
    from copilot_model_provider.runtimes.base import RuntimeAdapter

_AUTHORIZATION_HEADER_NAME = 'Authorization'


def install_openai_chat_route(
    app: FastAPI,
    *,
    model_router: ModelRouter,
    runtime_adapter: RuntimeAdapter,
) -> None:
    """Install the OpenAI-compatible ``POST /v1/chat/completions`` route."""

    async def _create_chat_completion(
        request: OpenAIChatCompletionRequest,
        authorization_header: Annotated[
            str | None,
            Header(alias=_AUTHORIZATION_HEADER_NAME),
        ] = None,
    ) -> OpenAIChatCompletionResponse | StreamingResponse:
        """Execute a chat completion through the runtime adapter."""
        request_id = uuid4().hex
        route = model_router.resolve_model(alias=request.model)
        runtime_auth_token = normalize_bearer_token(value=authorization_header)
        canonical_request = normalize_openai_chat_request(
            request=request,
            request_id=request_id,
        ).model_copy(update={'runtime_auth_token': runtime_auth_token})
        if canonical_request.stream:
            return await _create_streaming_chat_completion(
                request=request,
                runtime_adapter=runtime_adapter,
                route=route,
                canonical_request=canonical_request,
            )

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


async def _create_streaming_chat_completion(
    *,
    request: OpenAIChatCompletionRequest,
    runtime_adapter: RuntimeAdapter,
    route: ResolvedRoute,
    canonical_request: CanonicalChatRequest,
) -> StreamingResponse:
    """Create a streaming OpenAI-compatible SSE response."""
    runtime_stream = None
    try:
        runtime_stream = await runtime_adapter.stream_chat(
            request=canonical_request,
            route=route,
        )
        completion_id = f'chatcmpl-{uuid4().hex}'
        created = int(time())
    except Exception:
        if runtime_stream is not None:
            await close_runtime_event_stream(runtime_stream=runtime_stream)
        raise

    async def _frame_stream() -> AsyncIterator[str]:
        """Yield OpenAI-compatible SSE frames for one streaming chat response."""
        emit_role = True
        async for event in runtime_stream.events:
            stream_event = translate_session_event(event=event)
            if stream_event is None:
                continue

            if isinstance(stream_event, StreamingErrorEvent):
                yield encode_sse_event(
                    data=json.dumps(
                        {
                            'error': {
                                'code': stream_event.code,
                                'message': stream_event.message,
                            }
                        }
                    )
                )
                return

            chunks = translate_stream_event_to_openai_chunks(
                event=stream_event,
                completion_id=completion_id,
                model=request.model,
                emit_role=emit_role,
                created=created,
            )
            if chunks:
                emit_role = False

            for chunk in chunks:
                yield encode_openai_chat_chunk(chunk=chunk)

        yield encode_openai_done_event()

    return StreamingResponse(_frame_stream(), media_type='text/event-stream')
