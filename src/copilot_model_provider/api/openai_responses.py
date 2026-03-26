"""OpenAI-compatible Responses endpoint."""

from __future__ import annotations

from time import time
from typing import TYPE_CHECKING, Annotated
from uuid import uuid4

from fastapi import Header
from fastapi.responses import StreamingResponse

from copilot_model_provider.api.shared import (
    close_runtime_event_stream,
    normalize_bearer_token,
    normalize_optional_header_value,
    resolve_session_lock_manager,
    resolve_session_map,
    should_skip_aggregated_assistant_message,
)
from copilot_model_provider.core.models import (
    OpenAIResponse,
    OpenAIResponsesCreateRequest,
    build_bearer_token_subject,
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
from copilot_model_provider.core.sessions import (
    ManagedExecutionSession,
    persist_execution_session,
    prepare_execution_session,
    release_execution_session,
)
from copilot_model_provider.streaming.events import (
    AssistantTextDeltaEvent,
    StreamingErrorEvent,
)
from copilot_model_provider.streaming.responses import (
    encode_openai_responses_error_event,
    encode_openai_responses_event,
)
from copilot_model_provider.streaming.translators import translate_session_event

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import FastAPI

    from copilot_model_provider.core.models import ResolvedRoute
    from copilot_model_provider.core.routing import ModelRouter
    from copilot_model_provider.runtimes.base import RuntimeAdapter, RuntimeEventStream
    from copilot_model_provider.storage import SessionMap

_SESSION_ID_HEADER_NAME = 'session_id'
_AUTHORIZATION_HEADER_NAME = 'Authorization'
_CLIENT_REQUEST_ID_HEADER_NAME = 'x-client-request-id'


def install_openai_responses_route(
    app: FastAPI,
    *,
    model_router: ModelRouter,
    runtime_adapter: RuntimeAdapter,
) -> None:
    """Install the OpenAI-compatible ``POST /v1/responses`` route.

    Args:
        app: The application instance that should serve the Responses endpoint.
        model_router: Router used to resolve the public ``model`` alias.
        runtime_adapter: Backend adapter that executes the normalized request.

    """

    async def _create_response(
        request: OpenAIResponsesCreateRequest,
        session_id_header: Annotated[
            str | None,
            Header(alias=_SESSION_ID_HEADER_NAME),
        ] = None,
        authorization_header: Annotated[
            str | None,
            Header(alias=_AUTHORIZATION_HEADER_NAME),
        ] = None,
        client_request_id_header: Annotated[
            str | None,
            Header(alias=_CLIENT_REQUEST_ID_HEADER_NAME),
        ] = None,
    ) -> OpenAIResponse | StreamingResponse:
        """Execute a Responses request through the existing runtime adapter."""
        request_id = normalize_optional_header_value(value=client_request_id_header)
        if request_id is None:
            request_id = uuid4().hex

        route = model_router.resolve_model(alias=request.model)
        runtime_auth_token = normalize_bearer_token(value=authorization_header)
        conversation_id = _resolve_responses_conversation_id(
            request=request,
            session_id_header=session_id_header,
        )
        canonical_request = normalize_openai_responses_request(
            request=request,
            request_id=request_id,
            conversation_id=conversation_id,
            execution_mode=route.session_mode,
        ).model_copy(
            update={
                'runtime_auth_token': runtime_auth_token,
                'auth_subject': (
                    build_bearer_token_subject(token=runtime_auth_token)
                    if runtime_auth_token is not None
                    else None
                ),
            }
        )
        managed_session = await prepare_execution_session(
            request=canonical_request,
            route=route,
            session_map=resolve_session_map(app),
            session_lock_manager=resolve_session_lock_manager(app),
        )
        if request.stream:
            return await _create_streaming_response(
                request=request,
                runtime_adapter=runtime_adapter,
                route=route,
                managed_session=managed_session,
                session_map=resolve_session_map(app),
            )

        try:
            completion = await runtime_adapter.complete_chat(
                request=managed_session.request,
                route=route,
            )
            persist_execution_session(
                managed_session=managed_session,
                session_map=resolve_session_map(app),
                runtime_name=route.runtime,
                runtime_model_id=route.runtime_model_id,
                session_id=completion.session_id,
            )
            return build_openai_responses_response_from_completion(
                request=request,
                completion=completion,
                response_id=build_response_id(
                    request_id=managed_session.request.request_id
                ),
                conversation_id=managed_session.request.conversation_id,
            )
        finally:
            await release_execution_session(managed_session=managed_session)

    app.add_api_route(
        '/v1/responses',
        _create_response,
        methods=['POST'],
        response_model=OpenAIResponse,
    )


async def _create_streaming_response(
    *,
    request: OpenAIResponsesCreateRequest,
    runtime_adapter: RuntimeAdapter,
    route: ResolvedRoute,
    managed_session: ManagedExecutionSession,
    session_map: SessionMap | None,
) -> StreamingResponse:
    """Create a streaming OpenAI Responses-compatible SSE response."""
    runtime_stream: RuntimeEventStream | None = None
    try:
        runtime_stream = await runtime_adapter.stream_chat(
            request=managed_session.request,
            route=route,
        )
        persist_execution_session(
            managed_session=managed_session,
            session_map=session_map,
            runtime_name=managed_session.route.runtime,
            runtime_model_id=managed_session.route.runtime_model_id,
            session_id=runtime_stream.session_id,
        )
        response_id = build_response_id(request_id=managed_session.request.request_id)
        created_at = int(time())
    except Exception:
        if runtime_stream is not None:
            await close_runtime_event_stream(runtime_stream=runtime_stream)
        await release_execution_session(managed_session=managed_session)
        raise

    async def _frame_stream() -> AsyncIterator[str]:
        """Yield OpenAI Responses-compatible SSE frames for one stream."""
        sequence_number = 0
        completed_at = created_at
        output_parts: list[str] = []
        completion_emitted = False
        saw_text_delta = False
        try:
            yield encode_openai_responses_event(
                payload=build_openai_responses_created_event(
                    request=request,
                    response_id=response_id,
                    sequence_number=sequence_number,
                    conversation_id=managed_session.request.conversation_id,
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

            async for event in runtime_stream.events:
                if should_skip_aggregated_assistant_message(
                    event=event,
                    saw_text_delta=saw_text_delta,
                ):
                    continue

                stream_event = translate_session_event(event=event)
                if stream_event is None:
                    continue

                if isinstance(stream_event, StreamingErrorEvent):
                    yield encode_openai_responses_error_event(
                        code=stream_event.code,
                        message=stream_event.message,
                    )
                    return

                if isinstance(stream_event, AssistantTextDeltaEvent):
                    saw_text_delta = True
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
                        conversation_id=managed_session.request.conversation_id,
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
                        conversation_id=managed_session.request.conversation_id,
                        created_at=created_at,
                        completed_at=completed_at,
                    ).model_dump_json(exclude_none=True)
                )
        finally:
            await release_execution_session(managed_session=managed_session)

    return StreamingResponse(_frame_stream(), media_type='text/event-stream')


def _resolve_responses_conversation_id(
    *,
    request: OpenAIResponsesCreateRequest,
    session_id_header: str | None,
) -> str | None:
    """Resolve the northbound conversation identifier for one Responses request.

    Args:
        request: Validated Responses request body.
        session_id_header: Optional Codex-style session identifier header.

    Returns:
        The normalized conversation identifier that should be used for internal
        session persistence, if one was supplied by the client.

    """
    return normalize_optional_header_value(
        value=session_id_header
    ) or normalize_optional_header_value(value=request.previous_response_id)
