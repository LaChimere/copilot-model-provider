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
from copilot_model_provider.core.errors import ProviderError
from copilot_model_provider.core.models import (
    CanonicalChatRequest,
    OpenAIResponse,
    OpenAIResponsesCreateRequest,
    OpenAIResponsesInputMessage,
    ResolvedRoute,
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
        session_id = _pop_pending_session_id(
            pending_sessions_by_response_id=pending_sessions_by_response_id,
            previous_response_id=request.previous_response_id,
        )
        canonical_request = normalize_openai_responses_request(
            request=request,
            request_id=request_id,
            session_id=session_id,
            runtime_auth_token=runtime_auth_token,
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
                pending_sessions_by_response_id=pending_sessions_by_response_id,
            )

        completion = await runtime.complete_chat(
            request=canonical_request,
            route=route,
        )
        response_id = build_response_id(request_id=canonical_request.request_id)
        if (
            completion.pending_tool_call is not None
            and completion.session_id is not None
        ):
            pending_sessions_by_response_id[response_id] = completion.session_id
        _logger.info(
            'openai_responses_completion_ready',
            request_id=request_id,
            response_id=response_id,
            session_id=completion.session_id,
            finish_reason=completion.finish_reason,
            output_text_chars=len(completion.output_text or ''),
            pending_tool_call_name=(
                completion.pending_tool_call.name
                if completion.pending_tool_call is not None
                else None
            ),
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
    pending_sessions_by_response_id: dict[str, str],
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
                completed_at = int(time())
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

                function_output_index = 1 if message_item_started else 0
                function_call_item = build_openai_responses_function_call_item(
                    response_id=response_id,
                    tool_call=stream_event.tool_call,
                )
                yield encode_openai_responses_event(
                    payload=build_openai_responses_output_item_added_event(
                        item=function_call_item,
                        sequence_number=sequence_number,
                        output_index=function_output_index,
                    ).model_dump_json(exclude_none=True)
                )
                sequence_number += 1
                yield encode_openai_responses_event(
                    payload=build_openai_responses_output_item_done_event(
                        item=function_call_item,
                        sequence_number=sequence_number,
                        output_index=function_output_index,
                    ).model_dump_json(exclude_none=True)
                )
                sequence_number += 1
                if runtime_stream.session_id is not None:
                    pending_sessions_by_response_id[response_id] = (
                        runtime_stream.session_id
                    )
                _logger.info(
                    'openai_responses_stream_tool_call_requested',
                    request_id=canonical_request.request_id,
                    response_id=response_id,
                    session_id=runtime_stream.session_id,
                    tool_call_id=stream_event.tool_call.call_id,
                    tool_name=stream_event.tool_call.name,
                    output_text_chars=len(''.join(output_parts)),
                    pending_response_session_count=len(pending_sessions_by_response_id),
                )
                yield encode_openai_responses_event(
                    payload=build_openai_responses_completed_event(
                        request=request,
                        response_id=response_id,
                        output_text=''.join(output_parts) or None,
                        pending_tool_call=stream_event.tool_call,
                        sequence_number=sequence_number,
                        created_at=created_at,
                        completed_at=completed_at,
                        usage=usage,
                    ).model_dump_json(exclude_none=True)
                )
                completion_emitted = True
                return

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

            yield encode_openai_responses_event(
                payload=build_openai_responses_completed_event(
                    request=request,
                    response_id=response_id,
                    output_text=''.join(output_parts) or None,
                    pending_tool_call=None,
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
            yield encode_openai_responses_event(
                payload=build_openai_responses_completed_event(
                    request=request,
                    response_id=response_id,
                    output_text=''.join(output_parts) or None,
                    pending_tool_call=None,
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


def _pop_pending_session_id(
    *,
    pending_sessions_by_response_id: dict[str, str],
    previous_response_id: str | None,
) -> str | None:
    """Resolve and consume one pending session continuation id."""
    if previous_response_id is None:
        return None

    session_id = pending_sessions_by_response_id.pop(previous_response_id, None)
    if session_id is None:
        raise ProviderError(
            code='invalid_previous_response_id',
            message='No pending provider session matched the supplied previous_response_id.',
            status_code=400,
        )
    _logger.info(
        'openai_responses_continuation_resolved',
        previous_response_id=previous_response_id,
        session_id=session_id,
        pending_response_session_count=len(pending_sessions_by_response_id),
    )
    return session_id


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
