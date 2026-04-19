"""OpenAI-compatible Responses endpoint."""

from __future__ import annotations

from time import time
from typing import TYPE_CHECKING, Annotated
from uuid import uuid4

import structlog
from fastapi import FastAPI, Header
from fastapi.responses import StreamingResponse

from copilot_model_provider.api.shared import (
    close_runtime_event_stream,
    iter_canonical_runtime_stream_events,
    normalize_optional_header_value,
    open_runtime_event_stream,
    resolve_runtime_auth_token,
)
from copilot_model_provider.core.continuations import (
    PENDING_CONTINUATION_TTL_SECONDS,
)
from copilot_model_provider.core.errors import ProviderError
from copilot_model_provider.core.models import (
    CanonicalChatRequest,
    CanonicalToolCall,
    OpenAIResponse,
    OpenAIResponsesCreateRequest,
    OpenAIResponsesFunctionCallOutputItem,
    OpenAIResponsesInputMessage,
    ResolvedRoute,
)
from copilot_model_provider.core.pending_turns import (
    InMemoryPendingTurnStore,
    PendingTurnStoreProtocol,
    build_paused_turn_record,
)
from copilot_model_provider.core.responses import (
    build_openai_responses_completed_event,
    build_openai_responses_content_part_added_event,
    build_openai_responses_content_part_done_event,
    build_openai_responses_created_event,
    build_openai_responses_function_call_item,
    build_openai_responses_output_item_added_event,
    build_openai_responses_output_item_done_event,
    build_openai_responses_output_message,
    build_openai_responses_output_text_delta_event,
    build_openai_responses_output_text_done_event,
    build_openai_responses_response_from_completion,
    build_openai_responses_usage,
    build_response_id,
    normalize_openai_responses_request,
)
from copilot_model_provider.streaming.events import (
    AssistantTextDeltaEvent,
    AssistantUsageEvent,
    StreamingErrorEvent,
    ToolCallRequestedEvent,
    ToolCallsRequestedEvent,
)
from copilot_model_provider.streaming.responses import (
    encode_openai_responses_error_event,
    encode_openai_responses_event,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Collection, Sequence

    from copilot_model_provider.core.routing import ModelRouterProtocol
    from copilot_model_provider.runtimes.protocols import RuntimeProtocol

_AUTHORIZATION_HEADER_NAME = 'Authorization'
_CLIENT_REQUEST_ID_HEADER_NAME = 'x-client-request-id'
_PENDING_RESPONSE_SESSION_TTL_SECONDS = PENDING_CONTINUATION_TTL_SECONDS
_logger = structlog.get_logger(__name__)


def install_openai_responses_route(
    app: FastAPI,
    *,
    default_runtime_auth_token: str | None = None,
    model_router: ModelRouterProtocol,
    runtime: RuntimeProtocol,
    path: str = '/openai/v1/responses',
) -> None:
    """Install the OpenAI-compatible ``POST /openai/v1/responses`` route."""
    pending_sessions_by_response_id: dict[str, str] = {}
    pending_sessions_by_tool_call_id: dict[str, str] = {}

    async def _expire_pending_response_session(session_id: str) -> None:
        """Expire one pending Responses turn and discard its runtime session."""
        cleared_response_ids = _pop_pending_response_ids_for_session(
            pending_sessions_by_response_id=pending_sessions_by_response_id,
            session_id=session_id,
        )
        cleared_tool_call_ids = _pop_pending_tool_call_ids_for_session(
            pending_sessions_by_tool_call_id=pending_sessions_by_tool_call_id,
            session_id=session_id,
        )
        await runtime.discard_interactive_session(
            session_id=session_id,
            disconnect=True,
        )
        _logger.info(
            'openai_responses_pending_session_expired',
            session_id=session_id,
            cleared_response_ids=cleared_response_ids,
            cleared_tool_call_ids=sorted(cleared_tool_call_ids),
            ttl_seconds=_PENDING_RESPONSE_SESSION_TTL_SECONDS,
        )

    pending_turn_store = InMemoryPendingTurnStore(
        on_expire=_expire_pending_response_session
    )

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
        """Execute a Responses request through the runtime."""
        request_id = normalize_optional_header_value(value=client_request_id_header)
        if request_id is None:
            request_id = uuid4().hex

        _logger.info(
            'openai_responses_request_received',
            request_id=request_id,
            **_summarize_openai_responses_request(request=request),
        )

        runtime_auth_token = resolve_runtime_auth_token(
            authorization_header=authorization_header,
            default_token=default_runtime_auth_token,
        )
        route = await model_router.resolve_model(
            model_id=request.model,
            runtime_auth_token=runtime_auth_token,
        )
        session_id, accepted_tool_result_call_ids = await _pop_pending_session_id(
            request=request,
            pending_turn_store=pending_turn_store,
            pending_sessions_by_response_id=pending_sessions_by_response_id,
            pending_sessions_by_tool_call_id=pending_sessions_by_tool_call_id,
            previous_response_id=request.previous_response_id,
        )
        canonical_request = normalize_openai_responses_request(
            request=request,
            request_id=request_id,
            session_id=session_id,
            runtime_auth_token=runtime_auth_token,
            accepted_tool_result_call_ids=accepted_tool_result_call_ids,
        )
        _logger.info(
            'openai_responses_request_normalized',
            request_id=request_id,
            route_runtime=route.runtime,
            route_model_id=route.runtime_model_id,
            **_summarize_canonical_request(request=canonical_request),
            pending_response_session_count=len(pending_sessions_by_response_id),
        )
        if request.stream:
            return await _create_streaming_response(
                request=request,
                runtime=runtime,
                route=route,
                canonical_request=canonical_request,
                pending_turn_store=pending_turn_store,
                pending_sessions_by_response_id=pending_sessions_by_response_id,
                pending_sessions_by_tool_call_id=pending_sessions_by_tool_call_id,
            )

        completion = await runtime.complete_chat(
            request=canonical_request,
            route=route,
        )
        response_id = build_response_id()
        if completion.pending_tool_calls and completion.session_id is not None:
            await _remember_pending_response_tool_batch(
                response_id=response_id,
                session_id=completion.session_id,
                pending_tool_calls=completion.pending_tool_calls,
                request_model_id=request.model,
                runtime_model_id=route.runtime_model_id or request.model,
                runtime_auth_token=runtime_auth_token,
                pending_turn_store=pending_turn_store,
                pending_sessions_by_response_id=pending_sessions_by_response_id,
                pending_sessions_by_tool_call_id=pending_sessions_by_tool_call_id,
            )
        _logger.info(
            'openai_responses_completion_ready',
            request_id=request_id,
            response_id=response_id,
            session_id=completion.session_id,
            finish_reason=completion.finish_reason,
            output_text_chars=len(completion.output_text or ''),
            pending_tool_call_count=len(completion.pending_tool_calls),
            pending_tool_call_names=[
                tool_call.name for tool_call in completion.pending_tool_calls
            ],
            pending_response_session_count=len(pending_sessions_by_response_id),
        )
        return build_openai_responses_response_from_completion(
            request=request,
            completion=completion,
            response_id=response_id,
        )

    app.add_api_route(
        path,
        _create_response,
        methods=['POST'],
        response_model=OpenAIResponse,
    )


async def _create_streaming_response(  # noqa: C901
    *,
    request: OpenAIResponsesCreateRequest,
    runtime: RuntimeProtocol,
    route: ResolvedRoute,
    canonical_request: CanonicalChatRequest,
    pending_turn_store: PendingTurnStoreProtocol,
    pending_sessions_by_response_id: dict[str, str],
    pending_sessions_by_tool_call_id: dict[str, str],
) -> StreamingResponse:
    """Create a streaming OpenAI Responses-compatible SSE response."""
    runtime_stream = None
    try:
        runtime_stream = await open_runtime_event_stream(
            runtime=runtime,
            request=canonical_request,
            route=route,
        )
        response_id = build_response_id()
        created_at = int(time())
        _logger.info(
            'openai_responses_stream_started',
            request_id=canonical_request.request_id,
            response_id=response_id,
            session_id=runtime_stream.session_id,
            route_runtime=route.runtime,
            route_model_id=route.runtime_model_id,
            **_summarize_canonical_request(request=canonical_request),
        )
    except Exception:
        if runtime_stream is not None:
            await close_runtime_event_stream(runtime_stream=runtime_stream)
        raise

    async def _frame_stream() -> AsyncIterator[str]:  # noqa: C901
        """Yield OpenAI Responses-compatible SSE frames for one stream."""
        sequence_number = 0
        output_parts: list[str] = []
        completed_at = created_at
        usage = None
        message_item_started = False
        completion_emitted = False
        saw_tool_call = False
        pending_tool_calls: list[CanonicalToolCall] = []
        pending_tool_call_ids: set[str] = set()

        yield encode_openai_responses_event(
            payload=build_openai_responses_created_event(
                request=request,
                response_id=response_id,
                sequence_number=sequence_number,
                created_at=created_at,
            ).model_dump_json(exclude_none=True)
        )
        sequence_number += 1

        async for stream_event in iter_canonical_runtime_stream_events(
            runtime_stream=runtime_stream
        ):
            if isinstance(stream_event, StreamingErrorEvent):
                _logger.info(
                    'openai_responses_stream_error',
                    request_id=canonical_request.request_id,
                    response_id=response_id,
                    session_id=runtime_stream.session_id,
                    error_code=stream_event.code,
                )
                yield encode_openai_responses_error_event(
                    code=stream_event.code,
                    message=stream_event.message,
                )
                return

            if isinstance(stream_event, AssistantUsageEvent):
                usage = build_openai_responses_usage(
                    prompt_tokens=stream_event.prompt_tokens,
                    completion_tokens=stream_event.completion_tokens,
                )
                continue

            if isinstance(stream_event, AssistantTextDeltaEvent):
                if not message_item_started:
                    yield encode_openai_responses_event(
                        payload=build_openai_responses_output_item_added_event(
                            item=build_openai_responses_output_message(
                                response_id=response_id,
                                output_text='',
                                status='in_progress',
                            ),
                            sequence_number=sequence_number,
                            output_index=0,
                        ).model_dump_json(exclude_none=True)
                    )
                    sequence_number += 1
                    yield encode_openai_responses_event(
                        payload=build_openai_responses_content_part_added_event(
                            response_id=response_id,
                            sequence_number=sequence_number,
                            output_index=0,
                        ).model_dump_json(exclude_none=True)
                    )
                    sequence_number += 1
                    message_item_started = True

                output_parts.append(stream_event.text)
                yield encode_openai_responses_event(
                    payload=build_openai_responses_output_text_delta_event(
                        response_id=response_id,
                        text=stream_event.text,
                        sequence_number=sequence_number,
                        output_index=0,
                    ).model_dump_json(exclude_none=True)
                )
                sequence_number += 1
                continue

            if isinstance(stream_event, ToolCallRequestedEvent):
                saw_tool_call = True
                _append_unique_tool_calls(
                    pending_tool_calls=pending_tool_calls,
                    pending_tool_call_ids=pending_tool_call_ids,
                    tool_calls=(stream_event.tool_call,),
                )
                continue

            if isinstance(stream_event, ToolCallsRequestedEvent):
                saw_tool_call = True
                _append_unique_tool_calls(
                    pending_tool_calls=pending_tool_calls,
                    pending_tool_call_ids=pending_tool_call_ids,
                    tool_calls=stream_event.tool_calls,
                )
                continue

            completed_at = int(time())
            if usage is None:
                usage = build_openai_responses_usage(
                    prompt_tokens=stream_event.prompt_tokens,
                    completion_tokens=stream_event.completion_tokens,
                )
            if message_item_started:
                final_text = ''.join(output_parts)
                yield encode_openai_responses_event(
                    payload=build_openai_responses_output_text_done_event(
                        response_id=response_id,
                        text=final_text,
                        sequence_number=sequence_number,
                        output_index=0,
                    ).model_dump_json(exclude_none=True)
                )
                sequence_number += 1
                yield encode_openai_responses_event(
                    payload=build_openai_responses_content_part_done_event(
                        response_id=response_id,
                        text=final_text,
                        sequence_number=sequence_number,
                        output_index=0,
                    ).model_dump_json(exclude_none=True)
                )
                sequence_number += 1
                yield encode_openai_responses_event(
                    payload=build_openai_responses_output_item_done_event(
                        item=build_openai_responses_output_message(
                            response_id=response_id,
                            output_text=final_text,
                            status='completed',
                        ),
                        sequence_number=sequence_number,
                        output_index=0,
                    ).model_dump_json(exclude_none=True)
                )
                sequence_number += 1

            if pending_tool_calls:
                first_function_output_index = 1 if message_item_started else 0
                for output_index, pending_tool_call in enumerate(
                    pending_tool_calls,
                    start=first_function_output_index,
                ):
                    function_call_item = build_openai_responses_function_call_item(
                        response_id=response_id,
                        tool_call=pending_tool_call,
                    )
                    yield encode_openai_responses_event(
                        payload=build_openai_responses_output_item_added_event(
                            item=function_call_item,
                            sequence_number=sequence_number,
                            output_index=output_index,
                        ).model_dump_json(exclude_none=True)
                    )
                    sequence_number += 1
                    yield encode_openai_responses_event(
                        payload=build_openai_responses_output_item_done_event(
                            item=function_call_item,
                            sequence_number=sequence_number,
                            output_index=output_index,
                        ).model_dump_json(exclude_none=True)
                    )
                    sequence_number += 1
                if runtime_stream.session_id is not None:
                    await _remember_pending_response_tool_batch(
                        response_id=response_id,
                        session_id=runtime_stream.session_id,
                        pending_tool_calls=pending_tool_calls,
                        request_model_id=request.model,
                        runtime_model_id=route.runtime_model_id or request.model,
                        runtime_auth_token=canonical_request.runtime_auth_token,
                        pending_turn_store=pending_turn_store,
                        pending_sessions_by_response_id=pending_sessions_by_response_id,
                        pending_sessions_by_tool_call_id=pending_sessions_by_tool_call_id,
                    )
                _logger.info(
                    'openai_responses_stream_tool_calls_requested',
                    request_id=canonical_request.request_id,
                    response_id=response_id,
                    session_id=runtime_stream.session_id,
                    tool_call_ids=[
                        pending_tool_call.call_id
                        for pending_tool_call in pending_tool_calls
                    ],
                    tool_call_names=[
                        pending_tool_call.name
                        for pending_tool_call in pending_tool_calls
                    ],
                    output_text_chars=len(''.join(output_parts)),
                    pending_response_session_count=len(pending_sessions_by_response_id),
                )
                yield encode_openai_responses_event(
                    payload=build_openai_responses_completed_event(
                        request=request,
                        response_id=response_id,
                        output_text=''.join(output_parts) or None,
                        pending_tool_calls=pending_tool_calls,
                        sequence_number=sequence_number,
                        created_at=created_at,
                        completed_at=completed_at,
                        usage=usage,
                    ).model_dump_json(exclude_none=True)
                )
                completion_emitted = True
                return

            yield encode_openai_responses_event(
                payload=build_openai_responses_completed_event(
                    request=request,
                    response_id=response_id,
                    output_text=''.join(output_parts) or None,
                    pending_tool_calls=(),
                    sequence_number=sequence_number,
                    created_at=created_at,
                    completed_at=completed_at,
                    usage=usage,
                ).model_dump_json(exclude_none=True)
            )
            completion_emitted = True
            _logger.info(
                'openai_responses_stream_completed',
                request_id=canonical_request.request_id,
                response_id=response_id,
                session_id=runtime_stream.session_id,
                output_text_chars=len(''.join(output_parts)),
                saw_tool_call=saw_tool_call,
                pending_response_session_count=len(pending_sessions_by_response_id),
            )
            return

        if not completion_emitted:
            if pending_tool_calls:
                if message_item_started:
                    final_text = ''.join(output_parts)
                    yield encode_openai_responses_event(
                        payload=build_openai_responses_output_text_done_event(
                            response_id=response_id,
                            text=final_text,
                            sequence_number=sequence_number,
                            output_index=0,
                        ).model_dump_json(exclude_none=True)
                    )
                    sequence_number += 1
                    yield encode_openai_responses_event(
                        payload=build_openai_responses_content_part_done_event(
                            response_id=response_id,
                            text=final_text,
                            sequence_number=sequence_number,
                            output_index=0,
                        ).model_dump_json(exclude_none=True)
                    )
                    sequence_number += 1
                    yield encode_openai_responses_event(
                        payload=build_openai_responses_output_item_done_event(
                            item=build_openai_responses_output_message(
                                response_id=response_id,
                                output_text=final_text,
                                status='completed',
                            ),
                            sequence_number=sequence_number,
                            output_index=0,
                        ).model_dump_json(exclude_none=True)
                    )
                    sequence_number += 1
                first_function_output_index = 1 if message_item_started else 0
                for output_index, pending_tool_call in enumerate(
                    pending_tool_calls,
                    start=first_function_output_index,
                ):
                    function_call_item = build_openai_responses_function_call_item(
                        response_id=response_id,
                        tool_call=pending_tool_call,
                    )
                    yield encode_openai_responses_event(
                        payload=build_openai_responses_output_item_added_event(
                            item=function_call_item,
                            sequence_number=sequence_number,
                            output_index=output_index,
                        ).model_dump_json(exclude_none=True)
                    )
                    sequence_number += 1
                    yield encode_openai_responses_event(
                        payload=build_openai_responses_output_item_done_event(
                            item=function_call_item,
                            sequence_number=sequence_number,
                            output_index=output_index,
                        ).model_dump_json(exclude_none=True)
                    )
                    sequence_number += 1
                if runtime_stream.session_id is not None:
                    await _remember_pending_response_tool_batch(
                        response_id=response_id,
                        session_id=runtime_stream.session_id,
                        pending_tool_calls=pending_tool_calls,
                        request_model_id=request.model,
                        runtime_model_id=route.runtime_model_id or request.model,
                        runtime_auth_token=canonical_request.runtime_auth_token,
                        pending_turn_store=pending_turn_store,
                        pending_sessions_by_response_id=pending_sessions_by_response_id,
                        pending_sessions_by_tool_call_id=pending_sessions_by_tool_call_id,
                    )
            yield encode_openai_responses_event(
                payload=build_openai_responses_completed_event(
                    request=request,
                    response_id=response_id,
                    output_text=''.join(output_parts) or None,
                    pending_tool_calls=tuple(pending_tool_calls),
                    sequence_number=sequence_number,
                    created_at=created_at,
                    completed_at=completed_at,
                    usage=usage,
                ).model_dump_json(exclude_none=True)
            )
            _logger.info(
                'openai_responses_stream_completed',
                request_id=canonical_request.request_id,
                response_id=response_id,
                session_id=runtime_stream.session_id,
                output_text_chars=len(''.join(output_parts)),
                saw_tool_call=saw_tool_call,
                pending_response_session_count=len(pending_sessions_by_response_id),
            )

    return StreamingResponse(_frame_stream(), media_type='text/event-stream')


async def _pop_pending_session_id(  # noqa: C901
    *,
    request: OpenAIResponsesCreateRequest,
    pending_turn_store: PendingTurnStoreProtocol,
    pending_sessions_by_response_id: dict[str, str],
    pending_sessions_by_tool_call_id: dict[str, str],
    previous_response_id: str | None,
) -> tuple[str | None, frozenset[str] | None]:
    """Resolve and consume one pending session continuation id."""
    tool_result_call_ids = _extract_tool_result_call_ids(request=request)
    _validate_no_duplicate_tool_result_call_ids(
        tool_result_call_ids=tool_result_call_ids
    )
    if previous_response_id is None:
        if not tool_result_call_ids:
            return None, None

        matched_call_ids = frozenset(
            call_id
            for call_id in tool_result_call_ids
            if call_id in pending_sessions_by_tool_call_id
        )
        if not matched_call_ids:
            if _contains_historical_tool_result_replay(request=request):
                return None, frozenset()
            raise ProviderError(
                code='invalid_tool_result',
                message='No pending provider session matched the supplied function_call_output items.',
                status_code=400,
            )

        session_ids = {
            pending_sessions_by_tool_call_id[call_id] for call_id in matched_call_ids
        }
        if len(session_ids) != 1:
            raise ProviderError(
                code='invalid_tool_result',
                message='Function call output items referenced multiple pending provider sessions.',
                status_code=400,
            )

        session_id = next(iter(session_ids))
        record = await pending_turn_store.get(session_id=session_id)
        if record is None:
            _pop_pending_tool_call_ids_for_session(
                pending_sessions_by_tool_call_id=pending_sessions_by_tool_call_id,
                session_id=session_id,
            )
            _pop_pending_response_ids_for_session(
                pending_sessions_by_response_id=pending_sessions_by_response_id,
                session_id=session_id,
            )
            raise ProviderError(
                code='invalid_tool_result',
                message='No pending provider session matched the supplied function_call_output items.',
                status_code=400,
            )
        if matched_call_ids != record.tool_ids:
            raise ProviderError(
                code='invalid_tool_result',
                message='Function call output items must provide the full pending tool-result batch.',
                status_code=400,
            )
        resolution = await pending_turn_store.resolve(tool_ids=matched_call_ids)
        if resolution.status != 'ready_to_resume' or resolution.record is None:
            raise ProviderError(
                code='invalid_tool_result',
                message='No pending provider session matched the supplied function_call_output items.',
                status_code=400,
            )
        cleared_response_ids = _pop_pending_response_ids_for_session(
            pending_sessions_by_response_id=pending_sessions_by_response_id,
            session_id=session_id,
        )
        _pop_pending_tool_call_ids_for_session(
            pending_sessions_by_tool_call_id=pending_sessions_by_tool_call_id,
            session_id=session_id,
            tool_call_ids=resolution.record.tool_ids,
        )
        _logger.info(
            'openai_responses_continuation_resolved',
            previous_response_id=None,
            tool_result_call_ids=matched_call_ids,
            cleared_response_ids=cleared_response_ids,
            session_id=session_id,
            pending_response_session_count=len(pending_sessions_by_response_id),
            pending_tool_call_session_count=len(pending_sessions_by_tool_call_id),
        )
        return session_id, matched_call_ids

    session_id = pending_sessions_by_response_id.get(previous_response_id)
    if session_id is None:
        raise ProviderError(
            code='invalid_previous_response_id',
            message='No pending provider session matched the supplied previous_response_id.',
            status_code=400,
        )

    known_call_ids = frozenset(
        call_id
        for call_id in tool_result_call_ids
        if call_id in pending_sessions_by_tool_call_id
    )
    mismatched_call_ids = [
        call_id
        for call_id in known_call_ids
        if pending_sessions_by_tool_call_id[call_id] != session_id
    ]
    if mismatched_call_ids:
        raise ProviderError(
            code='invalid_tool_result',
            message='Function call output items did not match the supplied previous_response_id.',
            status_code=400,
        )
    matched_call_ids = frozenset(
        call_id
        for call_id in tool_result_call_ids
        if pending_sessions_by_tool_call_id.get(call_id) == session_id
    )
    record = await pending_turn_store.get(session_id=session_id)
    if record is None:
        _pop_pending_response_ids_for_session(
            pending_sessions_by_response_id=pending_sessions_by_response_id,
            session_id=session_id,
        )
        _pop_pending_tool_call_ids_for_session(
            pending_sessions_by_tool_call_id=pending_sessions_by_tool_call_id,
            session_id=session_id,
        )
        raise ProviderError(
            code='invalid_previous_response_id',
            message='No pending provider session matched the supplied previous_response_id.',
            status_code=400,
        )
    if matched_call_ids != record.tool_ids:
        raise ProviderError(
            code='invalid_tool_result',
            message='Function call output items must provide the full pending tool-result batch.',
            status_code=400,
        )
    resolution = await pending_turn_store.resolve(
        tool_ids=matched_call_ids,
        expected_session_id=session_id,
    )
    if resolution.status != 'ready_to_resume' or resolution.record is None:
        raise ProviderError(
            code='invalid_previous_response_id',
            message='No pending provider session matched the supplied previous_response_id.',
            status_code=400,
        )
    cleared_response_ids = _pop_pending_response_ids_for_session(
        pending_sessions_by_response_id=pending_sessions_by_response_id,
        session_id=session_id,
    )
    _pop_pending_tool_call_ids_for_session(
        pending_sessions_by_tool_call_id=pending_sessions_by_tool_call_id,
        session_id=session_id,
        tool_call_ids=resolution.record.tool_ids,
    )
    _logger.info(
        'openai_responses_continuation_resolved',
        previous_response_id=previous_response_id,
        tool_result_call_ids=matched_call_ids,
        cleared_response_ids=cleared_response_ids,
        session_id=session_id,
        pending_response_session_count=len(pending_sessions_by_response_id),
        pending_tool_call_session_count=len(pending_sessions_by_tool_call_id),
    )
    return session_id, matched_call_ids


def _contains_historical_tool_result_replay(
    *,
    request: OpenAIResponsesCreateRequest,
) -> bool:
    """Report whether a request mixes unmatched tool outputs with replayed history."""
    if not isinstance(request.input, list):
        return False

    return any(isinstance(item, OpenAIResponsesInputMessage) for item in request.input)


def _extract_tool_result_call_ids(
    *, request: OpenAIResponsesCreateRequest
) -> list[str]:
    """Return function-call ids referenced by replayed tool results."""
    if not isinstance(request.input, list):
        return []

    return [
        item.call_id
        for item in request.input
        if isinstance(item, OpenAIResponsesFunctionCallOutputItem)
    ]


def _validate_no_duplicate_tool_result_call_ids(
    *,
    tool_result_call_ids: Sequence[str],
) -> None:
    """Reject malformed Responses continuations that repeat one call id."""
    if len(tool_result_call_ids) == len(set(tool_result_call_ids)):
        return

    raise ProviderError(
        code='invalid_tool_result',
        message='Function call output items must not repeat the same call_id.',
        status_code=400,
    )


async def _remember_pending_response_tool_batch(
    *,
    response_id: str,
    session_id: str,
    pending_tool_calls: Sequence[CanonicalToolCall],
    request_model_id: str,
    runtime_model_id: str,
    runtime_auth_token: str | None,
    pending_turn_store: PendingTurnStoreProtocol,
    pending_sessions_by_response_id: dict[str, str],
    pending_sessions_by_tool_call_id: dict[str, str],
) -> None:
    """Record one paused Responses turn so continuation requests can resume it."""
    await pending_turn_store.remember(
        record=build_paused_turn_record(
            session_id=session_id,
            tool_ids=tuple(
                pending_tool_call.call_id for pending_tool_call in pending_tool_calls
            ),
            request_model_id=request_model_id,
            runtime_model_id=runtime_model_id,
            runtime_auth_token=runtime_auth_token,
            expires_at=time() + _PENDING_RESPONSE_SESSION_TTL_SECONDS,
        )
    )
    pending_sessions_by_response_id[response_id] = session_id
    for pending_tool_call in pending_tool_calls:
        pending_sessions_by_tool_call_id[pending_tool_call.call_id] = session_id


def _append_unique_tool_calls(
    *,
    pending_tool_calls: list[CanonicalToolCall],
    pending_tool_call_ids: set[str],
    tool_calls: Sequence[CanonicalToolCall],
) -> None:
    """Append tool calls once per call id while preserving first-seen order."""
    for tool_call in tool_calls:
        if tool_call.call_id in pending_tool_call_ids:
            continue
        pending_tool_call_ids.add(tool_call.call_id)
        pending_tool_calls.append(tool_call)


def _pop_pending_response_ids_for_session(
    *,
    pending_sessions_by_response_id: dict[str, str],
    session_id: str,
) -> list[str]:
    """Remove response ids that still point at the resolved interactive session."""
    cleared_response_ids = [
        response_id
        for response_id, mapped_session_id in pending_sessions_by_response_id.items()
        if mapped_session_id == session_id
    ]
    for response_id in cleared_response_ids:
        pending_sessions_by_response_id.pop(response_id, None)
    return cleared_response_ids


def _pop_pending_tool_call_ids_for_session(
    *,
    pending_sessions_by_tool_call_id: dict[str, str],
    session_id: str,
    tool_call_ids: Collection[str] | None = None,
) -> list[str]:
    """Remove tool-call ids that still point at the resolved interactive session."""
    candidate_call_ids = (
        list(tool_call_ids)
        if tool_call_ids is not None
        else [
            call_id
            for call_id, mapped_session_id in pending_sessions_by_tool_call_id.items()
            if mapped_session_id == session_id
        ]
    )
    cleared_call_ids: list[str] = []
    for call_id in candidate_call_ids:
        if pending_sessions_by_tool_call_id.get(call_id) != session_id:
            continue
        pending_sessions_by_tool_call_id.pop(call_id, None)
        cleared_call_ids.append(call_id)
    return cleared_call_ids


def _summarize_openai_responses_request(
    *, request: OpenAIResponsesCreateRequest
) -> dict[str, object]:
    """Return a compact diagnostic summary for one public Responses request."""
    input_kind = 'string' if isinstance(request.input, str) else 'items'
    input_item_types: list[str] = []
    input_message_roles: list[str] = []
    input_content_part_types: list[str] = []
    input_tool_result_count = 0
    if isinstance(request.input, list):
        for item in request.input:
            input_item_types.append(item.type)
            if isinstance(item, OpenAIResponsesInputMessage):
                input_message_roles.append(item.role)
                content = item.content
                if isinstance(content, str):
                    input_content_part_types.append('text_string')
                else:
                    input_content_part_types.extend(part.type for part in content)
                continue
            if isinstance(item, OpenAIResponsesFunctionCallOutputItem):
                input_tool_result_count += 1

    instructions_kind = None
    if request.instructions is not None:
        instructions_kind = (
            'string' if isinstance(request.instructions, str) else 'messages'
        )

    return {
        'model': request.model,
        'stream': request.stream,
        'previous_response_id': request.previous_response_id,
        'tool_count': len(request.tools),
        'tool_names': [tool.get('name') or tool.get('type') for tool in request.tools],
        'input_kind': input_kind,
        'input_item_types': input_item_types,
        'input_message_roles': input_message_roles,
        'input_content_part_types': input_content_part_types,
        'input_tool_result_count': input_tool_result_count,
        'instructions_kind': instructions_kind,
    }


def _summarize_canonical_request(*, request: CanonicalChatRequest) -> dict[str, object]:
    """Return a compact diagnostic summary for one canonical Responses request."""
    return {
        'canonical_session_id': request.session_id,
        'stream': request.stream,
        'message_count': len(request.messages),
        'message_roles': [message.role for message in request.messages],
        'tool_definition_count': len(request.tool_definitions),
        'tool_definition_names': [tool.name for tool in request.tool_definitions],
        'tool_result_count': len(request.tool_results),
        'tool_routing_mode': request.tool_routing_policy.mode,
        'excluded_builtin_tools': list(
            request.tool_routing_policy.excluded_builtin_tools
        ),
        'has_guidance': request.tool_routing_policy.guidance is not None,
    }
