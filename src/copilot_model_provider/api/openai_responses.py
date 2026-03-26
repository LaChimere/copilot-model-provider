"""OpenAI-compatible Responses endpoint."""

from __future__ import annotations

from time import time
from typing import TYPE_CHECKING, Annotated
from uuid import uuid4

from fastapi import FastAPI, Header
from fastapi.responses import StreamingResponse

from copilot_model_provider.api.shared import (
    close_runtime_event_stream,
    iter_canonical_runtime_stream_events,
    normalize_bearer_token,
    normalize_optional_header_value,
    open_runtime_event_stream,
)
from copilot_model_provider.core.models import (
    CanonicalChatRequest,
    OpenAIResponse,
    OpenAIResponsesCreateRequest,
    ResolvedRoute,
)
from copilot_model_provider.core.responses import (
    build_openai_responses_completed_event,
    build_openai_responses_content_part_added_event,
    build_openai_responses_content_part_done_event,
    build_openai_responses_created_event,
    build_openai_responses_output_item_added_event,
    build_openai_responses_output_item_done_event,
    build_openai_responses_output_text_delta_event,
    build_openai_responses_response_from_completion,
    build_response_id,
    normalize_openai_responses_request,
)
from copilot_model_provider.streaming.events import (
    AssistantTextDeltaEvent,
    StreamingErrorEvent,
)
from copilot_model_provider.streaming.responses import (
    encode_openai_responses_error_event,
    encode_openai_responses_event,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from copilot_model_provider.core.routing import ModelRouterProtocol
    from copilot_model_provider.runtimes.protocols import RuntimeProtocol

_AUTHORIZATION_HEADER_NAME = 'Authorization'
_CLIENT_REQUEST_ID_HEADER_NAME = 'x-client-request-id'


def install_openai_responses_route(
    app: FastAPI,
    *,
    model_router: ModelRouterProtocol,
    runtime: RuntimeProtocol,
) -> None:
    """Install the OpenAI-compatible ``POST /v1/responses`` route."""

    async def _create_response(
        request: OpenAIResponsesCreateRequest,
        authorization_header: Annotated[
            str | None,
            Header(alias=_AUTHORIZATION_HEADER_NAME),
        ] = None,
        client_request_id_header: Annotated[
            str | None,
            Header(alias=_CLIENT_REQUEST_ID_HEADER_NAME),
        ] = None,
    ) -> OpenAIResponse | StreamingResponse:
        """Execute a Responses request through the existing runtime."""
        request_id = normalize_optional_header_value(value=client_request_id_header)
        if request_id is None:
            request_id = uuid4().hex

        route = model_router.resolve_model(alias=request.model)
        runtime_auth_token = normalize_bearer_token(value=authorization_header)
        canonical_request = normalize_openai_responses_request(
            request=request,
            request_id=request_id,
            runtime_auth_token=runtime_auth_token,
        )
        if request.stream:
            return await _create_streaming_response(
                request=request,
                runtime=runtime,
                route=route,
                canonical_request=canonical_request,
            )

        completion = await runtime.complete_chat(
            request=canonical_request,
            route=route,
        )
        return build_openai_responses_response_from_completion(
            request=request,
            completion=completion,
            response_id=build_response_id(request_id=canonical_request.request_id),
        )

    app.add_api_route(
        '/v1/responses',
        _create_response,
        methods=['POST'],
        response_model=OpenAIResponse,
    )


async def _create_streaming_response(
    *,
    request: OpenAIResponsesCreateRequest,
    runtime: RuntimeProtocol,
    route: ResolvedRoute,
    canonical_request: CanonicalChatRequest,
) -> StreamingResponse:
    """Create a streaming OpenAI Responses-compatible SSE response."""
    runtime_stream = None
    try:
        runtime_stream = await open_runtime_event_stream(
            runtime=runtime,
            request=canonical_request,
            route=route,
        )
        response_id = build_response_id(request_id=canonical_request.request_id)
        created_at = int(time())
    except Exception:
        if runtime_stream is not None:
            await close_runtime_event_stream(runtime_stream=runtime_stream)
        raise

    async def _frame_stream() -> AsyncIterator[str]:
        """Yield OpenAI Responses-compatible SSE frames for one stream."""
        sequence_number = 0
        completed_at = created_at
        output_parts: list[str] = []
        completion_emitted = False
        yield encode_openai_responses_event(
            payload=build_openai_responses_created_event(
                request=request,
                response_id=response_id,
                sequence_number=sequence_number,
                created_at=created_at,
            ).model_dump_json(exclude_none=True)
        )
        sequence_number += 1
        yield encode_openai_responses_event(
            payload=build_openai_responses_output_item_added_event(
                response_id=response_id,
                sequence_number=sequence_number,
            ).model_dump_json(exclude_none=True)
        )
        sequence_number += 1
        yield encode_openai_responses_event(
            payload=build_openai_responses_content_part_added_event(
                response_id=response_id,
                sequence_number=sequence_number,
            ).model_dump_json(exclude_none=True)
        )
        sequence_number += 1

        async for stream_event in iter_canonical_runtime_stream_events(
            runtime_stream=runtime_stream
        ):
            if isinstance(stream_event, StreamingErrorEvent):
                yield encode_openai_responses_error_event(
                    code=stream_event.code,
                    message=stream_event.message,
                )
                return

            if isinstance(stream_event, AssistantTextDeltaEvent):
                output_parts.append(stream_event.text)
                yield encode_openai_responses_event(
                    payload=build_openai_responses_output_text_delta_event(
                        response_id=response_id,
                        text=stream_event.text,
                        sequence_number=sequence_number,
                    ).model_dump_json(exclude_none=True)
                )
                sequence_number += 1
                continue

            completed_at = int(time())
            final_text = ''.join(output_parts)
            yield encode_openai_responses_event(
                payload=build_openai_responses_content_part_done_event(
                    response_id=response_id,
                    text=final_text,
                    sequence_number=sequence_number,
                ).model_dump_json(exclude_none=True)
            )
            sequence_number += 1
            yield encode_openai_responses_event(
                payload=build_openai_responses_output_item_done_event(
                    response_id=response_id,
                    text=final_text,
                    sequence_number=sequence_number,
                ).model_dump_json(exclude_none=True)
            )
            sequence_number += 1
            yield encode_openai_responses_event(
                payload=build_openai_responses_completed_event(
                    request=request,
                    response_id=response_id,
                    output_text=final_text or None,
                    sequence_number=sequence_number,
                    created_at=created_at,
                    completed_at=completed_at,
                ).model_dump_json(exclude_none=True)
            )
            completion_emitted = True
            return

        if not completion_emitted:
            final_text = ''.join(output_parts)
            yield encode_openai_responses_event(
                payload=build_openai_responses_content_part_done_event(
                    response_id=response_id,
                    text=final_text,
                    sequence_number=sequence_number,
                ).model_dump_json(exclude_none=True)
            )
            sequence_number += 1
            yield encode_openai_responses_event(
                payload=build_openai_responses_output_item_done_event(
                    response_id=response_id,
                    text=final_text,
                    sequence_number=sequence_number,
                ).model_dump_json(exclude_none=True)
            )
            sequence_number += 1
            yield encode_openai_responses_event(
                payload=build_openai_responses_completed_event(
                    request=request,
                    response_id=response_id,
                    output_text=final_text or None,
                    sequence_number=sequence_number,
                    created_at=created_at,
                    completed_at=completed_at,
                ).model_dump_json(exclude_none=True)
            )

    return StreamingResponse(_frame_stream(), media_type='text/event-stream')
