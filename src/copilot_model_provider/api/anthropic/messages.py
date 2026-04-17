"""Anthropic-compatible Messages endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

import structlog
from fastapi import FastAPI, Header
from fastapi.responses import StreamingResponse

from copilot_model_provider.api.anthropic.protocol import (
    build_anthropic_content_block_delta_event,
    build_anthropic_content_block_start_event,
    build_anthropic_content_block_stop_event,
    build_anthropic_count_tokens_response,
    build_anthropic_message_delta_event,
    build_anthropic_message_id,
    build_anthropic_message_response_from_completion,
    build_anthropic_message_start_event,
    build_anthropic_message_stop_event,
    build_anthropic_tool_use_content_block,
    build_anthropic_usage,
    estimate_anthropic_input_tokens,
    estimate_anthropic_output_tokens,
    normalize_anthropic_messages_request,
)
from copilot_model_provider.api.shared import (
    AnthropicGatewayHeaders,
    close_runtime_event_stream,
    iter_canonical_runtime_stream_events,
    normalize_anthropic_gateway_headers,
    open_runtime_event_stream,
    resolve_runtime_auth_token_from_anthropic_headers,
)
from copilot_model_provider.core.errors import ProviderError
from copilot_model_provider.core.models import (
    AnthropicCountTokensResponse,
    AnthropicMessageResponse,
    AnthropicMessagesCountTokensRequest,
    AnthropicMessagesCreateRequest,
    AnthropicTextContentBlock,
    CanonicalChatRequest,
    CanonicalToolCall,
    ResolvedRoute,
)
from copilot_model_provider.streaming.anthropic import (
    encode_anthropic_error_event,
    encode_anthropic_event,
)
from copilot_model_provider.streaming.events import (
    AssistantTextDeltaEvent,
    AssistantUsageEvent,
    StreamingErrorEvent,
    ToolCallRequestedEvent,
    ToolCallsRequestedEvent,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from copilot_model_provider.core.routing import ModelRouterProtocol
    from copilot_model_provider.runtimes.protocols import RuntimeProtocol

_AUTHORIZATION_HEADER_NAME = 'Authorization'
_API_KEY_HEADER_NAME = 'X-Api-Key'
_ANTHROPIC_VERSION_HEADER_NAME = 'anthropic-version'
_ANTHROPIC_BETA_HEADER_NAME = 'anthropic-beta'
_CLAUDE_CODE_SESSION_ID_HEADER_NAME = 'X-Claude-Code-Session-Id'

_logger = structlog.get_logger(__name__)


def install_anthropic_messages_route(
    app: FastAPI,
    *,
    default_runtime_auth_token: str | None = None,
    model_router: ModelRouterProtocol,
    runtime: RuntimeProtocol,
    path: str = '/anthropic/v1/messages',
) -> None:
    """Install the Anthropic-compatible ``POST /anthropic/v1/messages`` route."""
    pending_sessions_by_tool_use_id: dict[str, str] = {}
    pending_tool_use_batches_by_session_id: dict[str, frozenset[str]] = {}

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
        anthropic_version_header: Annotated[
            str | None,
            Header(alias=_ANTHROPIC_VERSION_HEADER_NAME),
        ] = None,
        anthropic_beta_header: Annotated[
            str | None,
            Header(alias=_ANTHROPIC_BETA_HEADER_NAME),
        ] = None,
        claude_code_session_id_header: Annotated[
            str | None,
            Header(alias=_CLAUDE_CODE_SESSION_ID_HEADER_NAME),
        ] = None,
    ) -> AnthropicMessageResponse | StreamingResponse:
        """Execute an Anthropic Messages request through the runtime."""
        gateway_headers = normalize_anthropic_gateway_headers(
            anthropic_version_header=anthropic_version_header,
            anthropic_beta_header=anthropic_beta_header,
            claude_code_session_id_header=claude_code_session_id_header,
        )
        _logger.info(
            'anthropic_messages_request_received',
            **_summarize_anthropic_request(request=request),
        )
        _log_anthropic_gateway_headers(
            surface='messages', gateway_headers=gateway_headers
        )
        runtime_auth_token = resolve_runtime_auth_token_from_anthropic_headers(
            authorization_header=authorization_header,
            api_key_header=api_key_header,
            default_token=default_runtime_auth_token,
        )
        route = await model_router.resolve_model(
            model_id=request.model,
            runtime_auth_token=runtime_auth_token,
        )
        session_id, accepted_tool_result_ids = (
            _pop_pending_session_id_from_tool_results(
                request=request,
                pending_sessions_by_tool_use_id=pending_sessions_by_tool_use_id,
                pending_tool_use_batches_by_session_id=(
                    pending_tool_use_batches_by_session_id
                ),
            )
        )
        canonical_request = normalize_anthropic_messages_request(
            request=request,
            session_id=session_id,
            runtime_auth_token=runtime_auth_token,
            accepted_tool_result_ids=accepted_tool_result_ids or None,
        )
        _logger.info(
            'anthropic_messages_request_normalized',
            route_runtime=route.runtime,
            route_model_id=route.runtime_model_id,
            **_summarize_canonical_request(request=canonical_request),
            pending_tool_use_session_count=len(pending_sessions_by_tool_use_id),
        )
        if request.stream:
            return await _create_streaming_message(
                request=request,
                runtime=runtime,
                route=route,
                canonical_request=canonical_request,
                pending_sessions_by_tool_use_id=pending_sessions_by_tool_use_id,
                pending_tool_use_batches_by_session_id=(
                    pending_tool_use_batches_by_session_id
                ),
            )

        completion = await runtime.complete_chat(
            request=canonical_request,
            route=route,
        )
        if completion.pending_tool_calls and completion.session_id is not None:
            _remember_pending_tool_use_batch(
                session_id=completion.session_id,
                pending_tool_calls=completion.pending_tool_calls,
                pending_sessions_by_tool_use_id=pending_sessions_by_tool_use_id,
                pending_tool_use_batches_by_session_id=(
                    pending_tool_use_batches_by_session_id
                ),
            )
        _logger.info(
            'anthropic_messages_completion_ready',
            session_id=completion.session_id,
            finish_reason=completion.finish_reason,
            output_text_chars=len(completion.output_text or ''),
            pending_tool_call_count=len(completion.pending_tool_calls),
            pending_tool_call_names=[
                tool_call.name for tool_call in completion.pending_tool_calls
            ],
            pending_tool_use_session_count=len(pending_sessions_by_tool_use_id),
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
        anthropic_version_header: Annotated[
            str | None,
            Header(alias=_ANTHROPIC_VERSION_HEADER_NAME),
        ] = None,
        anthropic_beta_header: Annotated[
            str | None,
            Header(alias=_ANTHROPIC_BETA_HEADER_NAME),
        ] = None,
        claude_code_session_id_header: Annotated[
            str | None,
            Header(alias=_CLAUDE_CODE_SESSION_ID_HEADER_NAME),
        ] = None,
    ) -> AnthropicCountTokensResponse:
        """Return a best-effort Anthropic-compatible input-token count."""
        gateway_headers = normalize_anthropic_gateway_headers(
            anthropic_version_header=anthropic_version_header,
            anthropic_beta_header=anthropic_beta_header,
            claude_code_session_id_header=claude_code_session_id_header,
        )
        _log_anthropic_gateway_headers(
            surface='count_tokens',
            gateway_headers=gateway_headers,
        )
        _logger.info(
            'anthropic_count_tokens_requested',
            model=request.model,
            message_count=len(request.messages),
            tool_count=len(request.tools),
        )
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


async def _create_streaming_message(  # noqa: C901
    *,
    request: AnthropicMessagesCreateRequest,
    runtime: RuntimeProtocol,
    route: ResolvedRoute,
    canonical_request: CanonicalChatRequest,
    pending_sessions_by_tool_use_id: dict[str, str],
    pending_tool_use_batches_by_session_id: dict[str, frozenset[str]],
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
        _logger.info(
            'anthropic_messages_stream_started',
            message_id=message_id,
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
        """Yield Anthropic-compatible SSE frames for one streamed message."""
        estimated_input_tokens = estimate_anthropic_input_tokens(request=request)
        latest_usage = build_anthropic_usage(
            prompt_tokens=estimated_input_tokens,
            completion_tokens=0,
        )
        output_parts: list[str] = []
        pending_tool_calls: list[CanonicalToolCall] = []
        pending_tool_call_ids: set[str] = set()
        text_block_started = False
        active_text_block_index: int | None = None
        next_content_block_index = 0
        yield encode_anthropic_event(
            event='message_start',
            payload=build_anthropic_message_start_event(
                model=request.model,
                message_id=message_id,
                usage=latest_usage,
            ).model_dump_json(exclude_none=True),
        )
        async for stream_event in iter_canonical_runtime_stream_events(
            runtime_stream=runtime_stream
        ):
            if isinstance(stream_event, StreamingErrorEvent):
                _logger.info(
                    'anthropic_messages_stream_error',
                    message_id=message_id,
                    session_id=runtime_stream.session_id,
                )
                yield encode_anthropic_error_event(message=stream_event.message)
                return

            if isinstance(stream_event, AssistantUsageEvent):
                latest_usage = build_anthropic_usage(
                    prompt_tokens=(
                        stream_event.prompt_tokens
                        if stream_event.prompt_tokens is not None
                        else estimated_input_tokens
                    ),
                    completion_tokens=(
                        stream_event.completion_tokens
                        if stream_event.completion_tokens is not None
                        else estimate_anthropic_output_tokens(
                            output_text=''.join(output_parts) or ' '
                        )
                    ),
                )
                continue

            if isinstance(stream_event, AssistantTextDeltaEvent):
                if not text_block_started:
                    active_text_block_index = next_content_block_index
                    next_content_block_index += 1
                    yield encode_anthropic_event(
                        event='content_block_start',
                        payload=build_anthropic_content_block_start_event(
                            content_block=AnthropicTextContentBlock(text=''),
                            index=active_text_block_index,
                        ).model_dump_json(exclude_none=True),
                    )
                    text_block_started = True

                output_parts.append(stream_event.text)
                yield encode_anthropic_event(
                    event='content_block_delta',
                    payload=build_anthropic_content_block_delta_event(
                        text=stream_event.text,
                        index=active_text_block_index or 0,
                    ).model_dump_json(exclude_none=True),
                )
                continue

            if isinstance(stream_event, ToolCallRequestedEvent):
                _append_unique_tool_calls(
                    pending_tool_calls=pending_tool_calls,
                    pending_tool_call_ids=pending_tool_call_ids,
                    tool_calls=(stream_event.tool_call,),
                )
                continue

            if isinstance(stream_event, ToolCallsRequestedEvent):
                _append_unique_tool_calls(
                    pending_tool_calls=pending_tool_calls,
                    pending_tool_call_ids=pending_tool_call_ids,
                    tool_calls=stream_event.tool_calls,
                )
                continue

            if text_block_started:
                yield encode_anthropic_event(
                    event='content_block_stop',
                    payload=build_anthropic_content_block_stop_event(
                        index=active_text_block_index or 0
                    ).model_dump_json(exclude_none=True),
                )
                text_block_started = False
                active_text_block_index = None
            if pending_tool_calls:
                for pending_tool_call in pending_tool_calls:
                    tool_block_index = next_content_block_index
                    next_content_block_index += 1
                    tool_use_block = build_anthropic_tool_use_content_block(
                        tool_call=pending_tool_call
                    )
                    yield encode_anthropic_event(
                        event='content_block_start',
                        payload=build_anthropic_content_block_start_event(
                            content_block=tool_use_block,
                            index=tool_block_index,
                        ).model_dump_json(exclude_none=True),
                    )
                    yield encode_anthropic_event(
                        event='content_block_stop',
                        payload=build_anthropic_content_block_stop_event(
                            index=tool_block_index
                        ).model_dump_json(exclude_none=True),
                    )
                if runtime_stream.session_id is not None:
                    _remember_pending_tool_use_batch(
                        session_id=runtime_stream.session_id,
                        pending_tool_calls=pending_tool_calls,
                        pending_sessions_by_tool_use_id=pending_sessions_by_tool_use_id,
                        pending_tool_use_batches_by_session_id=(
                            pending_tool_use_batches_by_session_id
                        ),
                    )
                _logger.info(
                    'anthropic_messages_stream_tool_calls_requested',
                    message_id=message_id,
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
                    pending_tool_use_session_count=len(pending_sessions_by_tool_use_id),
                )
                yield encode_anthropic_event(
                    event='message_delta',
                    payload=build_anthropic_message_delta_event(
                        stop_reason='tool_use',
                        usage=latest_usage,
                    ).model_dump_json(exclude_none=True),
                )
                yield encode_anthropic_event(
                    event='message_stop',
                    payload=build_anthropic_message_stop_event().model_dump_json(
                        exclude_none=True
                    ),
                )
                _logger.info(
                    'anthropic_messages_stream_completed',
                    message_id=message_id,
                    session_id=runtime_stream.session_id,
                    output_text_chars=len(''.join(output_parts)),
                    saw_tool_call=True,
                    pending_tool_use_session_count=len(pending_sessions_by_tool_use_id),
                )
                return
            yield encode_anthropic_event(
                event='message_delta',
                payload=build_anthropic_message_delta_event(
                    stop_reason=stream_event.finish_reason,
                    usage=latest_usage
                    or build_anthropic_usage(
                        prompt_tokens=estimated_input_tokens,
                        completion_tokens=estimate_anthropic_output_tokens(
                            output_text=''.join(output_parts) or ' '
                        ),
                    ),
                ).model_dump_json(exclude_none=True),
            )
            yield encode_anthropic_event(
                event='message_stop',
                payload=build_anthropic_message_stop_event().model_dump_json(
                    exclude_none=True
                ),
            )
            _logger.info(
                'anthropic_messages_stream_completed',
                message_id=message_id,
                session_id=runtime_stream.session_id,
                output_text_chars=len(''.join(output_parts)),
                saw_tool_call=False,
                pending_tool_use_session_count=len(pending_sessions_by_tool_use_id),
            )
            return

        if pending_tool_calls:
            if text_block_started:
                yield encode_anthropic_event(
                    event='content_block_stop',
                    payload=build_anthropic_content_block_stop_event(
                        index=active_text_block_index or 0
                    ).model_dump_json(exclude_none=True),
                )
                text_block_started = False
                active_text_block_index = None
            for pending_tool_call in pending_tool_calls:
                tool_block_index = next_content_block_index
                next_content_block_index += 1
                tool_use_block = build_anthropic_tool_use_content_block(
                    tool_call=pending_tool_call
                )
                yield encode_anthropic_event(
                    event='content_block_start',
                    payload=build_anthropic_content_block_start_event(
                        content_block=tool_use_block,
                        index=tool_block_index,
                    ).model_dump_json(exclude_none=True),
                )
                yield encode_anthropic_event(
                    event='content_block_stop',
                    payload=build_anthropic_content_block_stop_event(
                        index=tool_block_index
                    ).model_dump_json(exclude_none=True),
                )
            if runtime_stream.session_id is not None:
                _remember_pending_tool_use_batch(
                    session_id=runtime_stream.session_id,
                    pending_tool_calls=pending_tool_calls,
                    pending_sessions_by_tool_use_id=pending_sessions_by_tool_use_id,
                    pending_tool_use_batches_by_session_id=(
                        pending_tool_use_batches_by_session_id
                    ),
                )
            yield encode_anthropic_event(
                event='message_delta',
                payload=build_anthropic_message_delta_event(
                    stop_reason='tool_use',
                    usage=latest_usage,
                ).model_dump_json(exclude_none=True),
            )
            yield encode_anthropic_event(
                event='message_stop',
                payload=build_anthropic_message_stop_event().model_dump_json(
                    exclude_none=True
                ),
            )

    return StreamingResponse(_frame_stream(), media_type='text/event-stream')


def _log_anthropic_gateway_headers(
    *,
    surface: str,
    gateway_headers: AnthropicGatewayHeaders,
) -> None:
    """Log Anthropic gateway headers when the client supplied meaningful values."""
    payload = gateway_headers.model_dump(exclude_none=True)
    if not payload:
        return

    _logger.info('anthropic_gateway_headers', surface=surface, **payload)


def _pop_pending_session_id_from_tool_results(
    *,
    request: AnthropicMessagesCreateRequest,
    pending_sessions_by_tool_use_id: dict[str, str],
    pending_tool_use_batches_by_session_id: dict[str, frozenset[str]],
) -> tuple[str | None, frozenset[str]]:
    """Resolve a pending provider session from Anthropic ``tool_result`` blocks."""
    tool_use_ids: list[str] = []
    for message in request.messages:
        if isinstance(message.content, str):
            continue
        for block in message.content:
            if block.get('type') != 'tool_result':
                continue
            tool_use_id = block.get('tool_use_id')
            if isinstance(tool_use_id, str) and tool_use_id:
                tool_use_ids.append(tool_use_id)

    if not tool_use_ids:
        return None, frozenset()

    matched_tool_use_ids = frozenset(
        tool_use_id
        for tool_use_id in tool_use_ids
        if tool_use_id in pending_sessions_by_tool_use_id
    )
    if not matched_tool_use_ids:
        raise ProviderError(
            code='invalid_tool_result',
            message='No pending provider session matched the supplied tool_result blocks.',
            status_code=400,
        )

    session_ids = {
        pending_sessions_by_tool_use_id[tool_use_id]
        for tool_use_id in matched_tool_use_ids
    }
    if len(session_ids) != 1:
        raise ProviderError(
            code='invalid_tool_result',
            message='Tool result blocks referenced multiple pending provider sessions.',
            status_code=400,
        )

    session_id = next(iter(session_ids))
    _validate_full_tool_result_batch(
        tool_use_ids=matched_tool_use_ids,
        session_id=session_id,
        pending_tool_use_batches_by_session_id=pending_tool_use_batches_by_session_id,
    )
    for tool_use_id in matched_tool_use_ids:
        pending_sessions_by_tool_use_id.pop(tool_use_id, None)
    _logger.info(
        'anthropic_messages_continuation_resolved',
        tool_use_ids=matched_tool_use_ids,
        session_id=session_id,
        pending_tool_use_session_count=len(pending_sessions_by_tool_use_id),
    )
    return session_id, matched_tool_use_ids


def _remember_pending_tool_use_batch(
    *,
    session_id: str,
    pending_tool_calls: Sequence[CanonicalToolCall],
    pending_sessions_by_tool_use_id: dict[str, str],
    pending_tool_use_batches_by_session_id: dict[str, frozenset[str]],
) -> None:
    """Record one paused Anthropic tool-use batch so later continuations can resume it."""
    pending_tool_use_batches_by_session_id[session_id] = frozenset(
        pending_tool_call.call_id for pending_tool_call in pending_tool_calls
    )
    for pending_tool_call in pending_tool_calls:
        pending_sessions_by_tool_use_id[pending_tool_call.call_id] = session_id


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


def _validate_full_tool_result_batch(
    *,
    tool_use_ids: frozenset[str],
    session_id: str,
    pending_tool_use_batches_by_session_id: dict[str, frozenset[str]],
) -> None:
    """Verify that one Anthropic continuation submits the full pending tool batch."""
    outstanding_tool_use_ids = pending_tool_use_batches_by_session_id.get(session_id)
    if outstanding_tool_use_ids is None:
        return
    if tool_use_ids != outstanding_tool_use_ids:
        raise ProviderError(
            code='invalid_tool_result',
            message='Tool result blocks must provide the full pending tool-result batch.',
            status_code=400,
        )
    pending_tool_use_batches_by_session_id.pop(session_id, None)


def _summarize_anthropic_request(
    *, request: AnthropicMessagesCreateRequest
) -> dict[str, object]:
    """Return a compact diagnostic summary for one Anthropic request."""
    message_roles = [message.role for message in request.messages]
    content_block_types: list[str] = []
    for message in request.messages:
        if isinstance(message.content, str):
            content_block_types.append('text_string')
            continue
        content_block_types.extend(
            type_name
            for type_name in (block.get('type') for block in message.content)
            if isinstance(type_name, str)
        )

    return {
        'model': request.model,
        'stream': request.stream,
        'message_count': len(request.messages),
        'message_roles': message_roles,
        'content_block_types': content_block_types,
        'tool_count': len(request.tools),
        'tool_names': [tool.get('name') for tool in request.tools],
        'system_kind': (
            None
            if request.system is None
            else 'string'
            if isinstance(request.system, str)
            else 'blocks'
        ),
    }


def _summarize_canonical_request(*, request: CanonicalChatRequest) -> dict[str, object]:
    """Return a compact diagnostic summary for one canonical Anthropic request."""
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
