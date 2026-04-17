"""Copilot SDK-backed runtime for chat execution."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast, override

import structlog
from copilot import CopilotClient, SubprocessConfig
from copilot.generated.session_events import (
    PermissionRequest,
    SessionEvent,
    SessionEventType,
)
from copilot.session import PermissionRequestResult
from copilot.tools import Tool, ToolInvocation, ToolResult

from copilot_model_provider.core.chat import render_prompt
from copilot_model_provider.core.errors import ProviderError
from copilot_model_provider.core.models import (
    CanonicalChatMessage,
    CanonicalChatRequest,
    CanonicalToolCall,
    CanonicalToolResult,
    CopilotModelBilling,
    CopilotModelCapabilities,
    CopilotModelLimits,
    CopilotModelMetadata,
    CopilotModelPolicy,
    CopilotModelSupports,
    CopilotModelVisionLimits,
    ResolvedRoute,
    RuntimeCompletion,
    RuntimeDiscoveredModel,
    RuntimeHealth,
)
from copilot_model_provider.runtimes.protocols import (
    RuntimeEventStream,
    RuntimeProtocol,
)
from copilot_model_provider.streaming.events import (
    AssistantTextDeltaEvent,
    AssistantTurnCompleteEvent,
    AssistantUsageEvent,
    ToolCallRequestedEvent,
    ToolCallsRequestedEvent,
)
from copilot_model_provider.streaming.translators import (
    assistant_message_has_tool_requests,
    translate_session_events,
)

if TYPE_CHECKING:
    from copilot.session import CopilotSession

_INTERACTIVE_TOOL_CONTINUATION_PROMPT = 'Continue.'
_INTERACTIVE_TOOL_BATCH_QUIET_WINDOW_SECONDS = 0.05
_logger = structlog.get_logger(__name__)

PermissionRequestHandler = Callable[
    [PermissionRequest, dict[str, str]],
    PermissionRequestResult | Awaitable[PermissionRequestResult],
]


def _new_pending_tool_calls() -> list[CanonicalToolCall]:
    """Create an empty typed list for pending tool calls."""
    return []


def _new_pending_tool_call_ids() -> set[str]:
    """Create an empty typed set for pending tool-call identifiers."""
    return set()


class CopilotRuntime(RuntimeProtocol):
    """Execute stateless chat completions through the installed Copilot SDK."""

    def __init__(
        self,
        *,
        client_factory: Callable[[], CopilotClient] | None = None,
        authenticated_client_factory: Callable[[str], CopilotClient] | None = None,
        timeout_seconds: float = 60.0,
        working_directory: str | None = None,
    ) -> None:
        """Initialize the runtime with lazy Copilot client construction.

        Args:
            client_factory: Optional factory used to construct the underlying
                Copilot client. Tests can override this with a fake SDK surface.
            authenticated_client_factory: Optional factory used to construct a
                subprocess-backed Copilot client for one request-scoped GitHub
                bearer token.
            timeout_seconds: Maximum wall-clock time to wait for a non-streaming
                assistant response.
            working_directory: Optional working directory forwarded into new
                ephemeral Copilot sessions.

        """
        self._runtime_name = 'copilot'
        self._client_factory = client_factory or self._build_default_client
        self._authenticated_client_factory = (
            authenticated_client_factory or self._build_authenticated_client
        )
        self._timeout_seconds = timeout_seconds
        self._working_directory = working_directory
        self._client: CopilotClient | None = None
        self._interactive_sessions: dict[
            str, CopilotRuntime._InteractiveCopilotSession
        ] = {}
        self._interactive_sessions_lock = asyncio.Lock()

    @property
    @override
    def runtime_name(self) -> str:
        """Return the stable runtime identifier exposed by this runtime."""
        return self._runtime_name

    @property
    def connection_mode(self) -> str:
        """Report the runtime connection mode used by this runtime."""
        return 'subprocess'

    @override
    def default_route(self) -> ResolvedRoute:
        """Return the default route for the Copilot-backed runtime."""
        return ResolvedRoute(runtime=self.runtime_name)

    @override
    async def check_health(self) -> RuntimeHealth:
        """Report whether the lazy Copilot client is already connected."""
        state = self._get_or_create_client().get_state()
        return RuntimeHealth(
            runtime=self.runtime_name,
            available=state == 'connected',
            detail=f'Copilot client state: {state}',
        )

    @override
    async def list_models(
        self,
        *,
        runtime_auth_token: str | None = None,
    ) -> tuple[RuntimeDiscoveredModel, ...]:
        """List the live Copilot model descriptors for one auth context."""
        resolved_client = await self._get_client_for_runtime_auth_token(
            runtime_auth_token=runtime_auth_token
        )
        await self._ensure_client_started(resolved_client.client)
        try:
            models = await resolved_client.client.list_models()
        except Exception as error:
            raise ProviderError(
                code='runtime_execution_failed',
                message=f'Copilot runtime model discovery failed: {error}',
                status_code=502,
            ) from error
        finally:
            if resolved_client.stop_on_close:
                await self._stop_client(resolved_client.client)

        return _normalize_runtime_models(models=models)

    @override
    async def list_model_ids(
        self,
        *,
        runtime_auth_token: str | None = None,
    ) -> tuple[str, ...]:
        """List the live Copilot model identifiers for one auth context."""
        models = await self.list_models(runtime_auth_token=runtime_auth_token)
        return tuple(model.id for model in models)

    @override
    async def complete_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeCompletion:
        """Execute a canonical chat request through an ephemeral Copilot session."""
        uses_interactive_session = self._uses_interactive_session(request=request)
        _logger.info(
            'copilot_runtime_complete_chat_started',
            route_runtime=route.runtime,
            route_model_id=route.runtime_model_id,
            uses_interactive_session=uses_interactive_session,
            **_summarize_canonical_request(request=request),
        )
        if uses_interactive_session:
            self._validate_interactive_request(request=request)
            return await self._complete_chat_with_interactive_session(
                request=request,
                route=route,
            )

        if route.runtime_model_id is None:
            raise ProviderError(
                code='runtime_route_invalid',
                message='Resolved route is missing a runtime model identifier.',
                status_code=500,
            )

        active_session = await self._open_session(
            request=request,
            route=route,
            streaming=False,
        )
        completion: RuntimeCompletion
        try:
            event = await active_session.session.send_and_wait(
                render_prompt(request=request),
                timeout=self._timeout_seconds,
            )
            completion = _build_runtime_completion(
                event=event,
                session_id=active_session.session.session_id,
            )
            _logger.info(
                'copilot_runtime_complete_chat_finished',
                route_runtime=route.runtime,
                route_model_id=route.runtime_model_id,
                session_id=completion.session_id,
                finish_reason=completion.finish_reason,
                output_text_chars=len(completion.output_text or ''),
                pending_tool_call_count=len(completion.pending_tool_calls),
                pending_tool_call_names=[
                    tool_call.name for tool_call in completion.pending_tool_calls
                ],
            )
        except TimeoutError as error:
            raise ProviderError(
                code='runtime_timeout',
                message=str(error),
                status_code=504,
            ) from error
        except ProviderError:
            raise
        except Exception as error:
            raise ProviderError(
                code='runtime_execution_failed',
                message=f'Copilot runtime execution failed: {error}',
                status_code=502,
            ) from error
        finally:
            await self._close_session(active_session=active_session)

        return completion

    @override
    async def stream_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeEventStream:
        """Execute a canonical streaming chat request through the Copilot SDK."""
        uses_interactive_session = self._uses_interactive_session(request=request)
        _logger.info(
            'copilot_runtime_stream_chat_started',
            route_runtime=route.runtime,
            route_model_id=route.runtime_model_id,
            uses_interactive_session=uses_interactive_session,
            **_summarize_canonical_request(request=request),
        )
        if uses_interactive_session:
            self._validate_interactive_request(request=request)
            return await self._stream_chat_with_interactive_session(
                request=request,
                route=route,
            )

        return await self._stream_chat_stateless(request=request, route=route)

    async def _stream_chat_stateless(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeEventStream:
        """Execute the original stateless streaming chat flow."""
        active_session = await self._open_session(
            request=request,
            route=route,
            streaming=True,
        )
        session_closed = False

        async def _finalize_session() -> None:
            """Close the Copilot session at most once."""
            nonlocal session_closed
            if session_closed:
                return

            session_closed = True
            await self._close_session(active_session=active_session)

        async def _event_stream() -> AsyncIterator[SessionEvent]:
            """Yield SDK events for one assistant turn and close the session cleanly."""
            queue: asyncio.Queue[SessionEvent] = asyncio.Queue()

            def _handle_event(event: SessionEvent) -> None:
                queue.put_nowait(event)

            unsubscribe = active_session.session.on(_handle_event)
            try:
                await active_session.session.send(render_prompt(request=request))
                while True:
                    try:
                        event = await asyncio.wait_for(
                            queue.get(),
                            timeout=self._timeout_seconds,
                        )
                    except TimeoutError as error:
                        raise ProviderError(
                            code='runtime_timeout',
                            message='Timed out while waiting for Copilot streaming events.',
                            status_code=504,
                        ) from error

                    yield event
                    if event.type in {
                        SessionEventType.ASSISTANT_TURN_END,
                        SessionEventType.SESSION_ERROR,
                        SessionEventType.SESSION_IDLE,
                    }:
                        _logger.info(
                            'copilot_runtime_stateless_stream_terminal_event',
                            session_id=active_session.session.session_id,
                            event_type=event.type,
                        )
                        break
            except ProviderError:
                raise
            except Exception as error:
                raise ProviderError(
                    code='runtime_execution_failed',
                    message=f'Copilot runtime execution failed: {error}',
                    status_code=502,
                ) from error
            finally:
                unsubscribe()
                await _finalize_session()

        return RuntimeEventStream(
            session_id=active_session.session.session_id,
            events=_event_stream(),
            close=_finalize_session,
        )

    @dataclass(frozen=True, slots=True)
    class _ResolvedCopilotClient:
        """Client selection result for one canonical request."""

        client: CopilotClient
        stop_on_close: bool = False

    @dataclass(frozen=True, slots=True)
    class _ActiveCopilotSession:
        """Opened Copilot session plus the client lifecycle policy that owns it."""

        session: CopilotSession
        client: CopilotRuntime._ResolvedCopilotClient

    @dataclass(slots=True)
    class _PendingToolCallState:
        """External tool call that is waiting on the northbound client."""

        tool_call_id: str
        tool_name: str
        arguments: Any
        future: asyncio.Future[ToolResult] | None = None
        submitted_result: ToolResult | None = None

    @dataclass(slots=True)
    class _InteractiveCopilotSession:
        """Long-lived Copilot session kept alive across tool turns."""

        active_session: CopilotRuntime._ActiveCopilotSession
        event_queue: asyncio.Queue[SessionEvent]
        pending_tool_calls: dict[str, CopilotRuntime._PendingToolCallState]

    @dataclass(slots=True)
    class _InteractiveCompletionState:
        """Accumulated state while consuming one interactive completion stream."""

        output_parts: list[str]
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        pending_tool_calls: list[CanonicalToolCall] = field(
            default_factory=_new_pending_tool_calls
        )
        pending_tool_call_ids: set[str] = field(
            default_factory=_new_pending_tool_call_ids
        )
        saw_text_delta: bool = False

    def _get_or_create_client(self) -> CopilotClient:
        """Build the lazy Copilot client on first use and cache it afterwards."""
        if self._client is None:
            self._client = self._client_factory()

        return self._client

    async def _ensure_client_started(self, client: CopilotClient) -> None:
        """Start the Copilot client when the lazy runtime has not connected yet."""
        state = client.get_state()
        if state == 'error':
            raise ProviderError(
                code='runtime_unhealthy',
                message='Copilot client is in an error state.',
                status_code=503,
            )

        if state == 'disconnected':
            await client.start()

    async def _open_session(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
        streaming: bool,
    ) -> _ActiveCopilotSession:
        """Open a Copilot session for one request."""
        if route.runtime_model_id is None:
            raise ProviderError(
                code='runtime_route_invalid',
                message='Resolved route is missing a runtime model identifier.',
                status_code=500,
            )

        resolved_client = await self._get_client_for_request(request=request)
        await self._ensure_client_started(resolved_client.client)
        create_session_kwargs: dict[str, Any] = {
            'on_permission_request': self._deny_permission_request,
            'model': route.runtime_model_id,
            'working_directory': self._working_directory,
            'streaming': streaming,
        }
        if request.tool_definitions:
            create_session_kwargs['tools'] = self._build_tool_definitions(
                request=request
            )
        return self._ActiveCopilotSession(
            session=await resolved_client.client.create_session(
                **create_session_kwargs
            ),
            client=resolved_client,
        )

    async def _close_session(
        self,
        *,
        active_session: _ActiveCopilotSession,
    ) -> None:
        """Close a Copilot session once the request has completed."""
        try:
            await active_session.session.disconnect()
        finally:
            if active_session.client.stop_on_close:
                await self._stop_client(active_session.client.client)

    async def _get_client_for_request(
        self,
        *,
        request: CanonicalChatRequest,
    ) -> _ResolvedCopilotClient:
        """Resolve the Copilot client that should execute one canonical request."""
        return await self._get_client_for_runtime_auth_token(
            runtime_auth_token=request.runtime_auth_token
        )

    async def _get_client_for_runtime_auth_token(
        self,
        *,
        runtime_auth_token: str | None,
    ) -> _ResolvedCopilotClient:
        """Resolve the Copilot client that should use one auth context."""
        if runtime_auth_token is None:
            return self._ResolvedCopilotClient(client=self._get_or_create_client())

        return self._ResolvedCopilotClient(
            client=self._authenticated_client_factory(runtime_auth_token),
            stop_on_close=True,
        )

    async def _stop_client(self, client: CopilotClient) -> None:
        """Stop a short-lived Copilot client once its request-scoped work is done."""
        await client.stop()

    def _build_default_client(self) -> CopilotClient:
        """Construct the default lazy Copilot client for production usage."""
        return CopilotClient(None, auto_start=False)

    def _build_authenticated_client(self, github_token: str) -> CopilotClient:
        """Construct a subprocess-backed Copilot client for one bearer token.

        Args:
            github_token: Request-scoped GitHub bearer token used for Copilot auth.

        Returns:
            A ``CopilotClient`` configured to spawn its own CLI subprocess
            with the provided GitHub token injected through SDK auth settings.

        """
        return CopilotClient(
            SubprocessConfig(
                cwd=self._working_directory,
                github_token=github_token,
            ),
            auto_start=False,
        )

    def _deny_permission_request(
        self,
        request: PermissionRequest,
        context: dict[str, str],
    ) -> PermissionRequestResult:
        """Deny runtime permission requests for the thin stateless provider."""
        del request, context
        return PermissionRequestResult(
            kind='denied-by-rules',
            message='Server-side tools and MCP are disabled for this provider.',
        )

    def _uses_interactive_session(self, *, request: CanonicalChatRequest) -> bool:
        """Report whether the request routing policy requires session continuity."""
        return request.tool_routing_policy.mode == 'client_passthrough'

    def _validate_interactive_request(self, *, request: CanonicalChatRequest) -> None:
        """Reject invalid tool-aware requests before opening or resuming sessions."""
        if request.tool_results and request.session_id is None:
            raise ProviderError(
                code='invalid_previous_response_id',
                message='Tool-result continuations require a live provider session.',
                status_code=400,
            )

    async def _complete_chat_with_interactive_session(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeCompletion:
        """Aggregate one interactive tool-aware turn into a runtime completion."""
        runtime_stream = await self._stream_chat_with_interactive_session(
            request=request,
            route=route,
        )
        state = self._InteractiveCompletionState(output_parts=[])
        try:
            async for event in runtime_stream.events:
                if self._consume_interactive_completion_event(
                    event=event,
                    state=state,
                ):
                    break
        finally:
            if not state.pending_tool_calls and runtime_stream.close is not None:
                await runtime_stream.close()

        if not state.output_parts and not state.pending_tool_calls:
            raise ProviderError(
                code='runtime_empty_response',
                message='Copilot runtime returned no assistant content.',
                status_code=502,
            )

        return RuntimeCompletion(
            output_text=''.join(state.output_parts) or None,
            finish_reason='tool_calls' if state.pending_tool_calls else 'stop',
            session_id=runtime_stream.session_id,
            pending_tool_calls=tuple(state.pending_tool_calls),
            prompt_tokens=state.prompt_tokens,
            completion_tokens=state.completion_tokens,
        )

    async def _stream_chat_with_interactive_session(  # noqa: C901
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeEventStream:
        """Return a persistent runtime stream that can pause at tool boundaries."""
        session_state = await self._get_or_create_interactive_session(
            request=request,
            route=route,
        )
        if request.tool_results:
            _logger.info(
                'copilot_runtime_interactive_tool_results_received',
                session_id=session_state.active_session.session.session_id,
                tool_result_count=len(request.tool_results),
                tool_result_call_ids=[
                    result.call_id for result in request.tool_results
                ],
            )
            await self._submit_interactive_tool_results(
                session_id=session_state.active_session.session.session_id,
                tool_results=request.tool_results,
            )

        session_id = session_state.active_session.session.session_id

        async def _event_stream() -> AsyncIterator[SessionEvent]:  # noqa: C901
            """Yield session events until a tool boundary or terminal turn is reached."""
            saw_visible_response = False
            continuation_prompt_sent = False
            saw_tool_call = False
            saw_text_delta = False
            preserve_session = False
            try:
                while True:
                    wait_timeout = (
                        _INTERACTIVE_TOOL_BATCH_QUIET_WINDOW_SECONDS
                        if saw_tool_call
                        else self._timeout_seconds
                    )
                    try:
                        event = await asyncio.wait_for(
                            session_state.event_queue.get(),
                            timeout=wait_timeout,
                        )
                    except TimeoutError as error:
                        if saw_tool_call:
                            preserve_session = True
                            _logger.info(
                                'copilot_runtime_interactive_tool_batch_settled',
                                session_id=session_id,
                                pending_tool_call_count=len(
                                    session_state.pending_tool_calls
                                ),
                            )
                            break
                        raise ProviderError(
                            code='runtime_timeout',
                            message='Timed out while waiting for Copilot streaming events.',
                            status_code=504,
                        ) from error

                    stream_events = translate_session_events(
                        event=event,
                        suppress_aggregate_message_text=(
                            saw_text_delta
                            and assistant_message_has_tool_requests(event=event)
                        ),
                    )
                    event_has_tool_call = False
                    for stream_event in stream_events:
                        if isinstance(
                            stream_event,
                            AssistantTextDeltaEvent
                            | ToolCallRequestedEvent
                            | ToolCallsRequestedEvent,
                        ):
                            saw_visible_response = True
                        if isinstance(stream_event, AssistantTextDeltaEvent):
                            saw_text_delta = True
                        if isinstance(
                            stream_event,
                            ToolCallRequestedEvent | ToolCallsRequestedEvent,
                        ):
                            event_has_tool_call = True

                    if self._should_send_interactive_continuation_prompt(
                        event=event,
                        has_tool_results=bool(request.tool_results),
                        saw_visible_response=saw_visible_response,
                        continuation_prompt_sent=continuation_prompt_sent,
                    ):
                        continuation_prompt_sent = True
                        _logger.info(
                            'copilot_runtime_interactive_continuation_prompt_sent',
                            session_id=session_id,
                            event_type=event.type,
                        )
                        await session_state.active_session.session.send(
                            _INTERACTIVE_TOOL_CONTINUATION_PROMPT
                        )
                        continue

                    yield event
                    if event_has_tool_call:
                        saw_tool_call = True
                        _logger.info(
                            'copilot_runtime_interactive_tool_boundary_reached',
                            session_id=session_id,
                            pending_tool_call_count=len(
                                session_state.pending_tool_calls
                            ),
                        )
                        continue
                    if event.type in {
                        SessionEventType.ASSISTANT_TURN_END,
                        SessionEventType.SESSION_ERROR,
                        SessionEventType.SESSION_IDLE,
                    }:
                        if (
                            saw_tool_call
                            and event.type != SessionEventType.SESSION_ERROR
                        ):
                            preserve_session = True
                            _logger.info(
                                'copilot_runtime_interactive_tool_batch_completed',
                                session_id=session_id,
                                event_type=event.type,
                                pending_tool_call_count=len(
                                    session_state.pending_tool_calls
                                ),
                            )
                            break
                        _logger.info(
                            'copilot_runtime_interactive_terminal_event',
                            session_id=session_id,
                            event_type=event.type,
                        )
                        await self._discard_interactive_session(
                            session_id=session_id,
                            disconnect=True,
                        )
                        break
            finally:
                if not preserve_session:
                    await self._discard_interactive_session(
                        session_id=session_id,
                        disconnect=True,
                    )

        async def _close() -> None:
            """Abort one persistent interactive session stream."""
            await self._discard_interactive_session(
                session_id=session_id,
                disconnect=True,
            )

        return RuntimeEventStream(
            session_id=session_id,
            events=_event_stream(),
            close=_close,
        )

    def _consume_interactive_completion_event(  # noqa: C901
        self,
        *,
        event: SessionEvent,
        state: _InteractiveCompletionState,
    ) -> bool:
        """Update aggregated completion state from one interactive session event."""
        if (
            state.saw_text_delta
            and event.type == SessionEventType.ASSISTANT_MESSAGE
            and not assistant_message_has_tool_requests(event=event)
        ):
            return False

        for stream_event in translate_session_events(
            event=event,
            suppress_aggregate_message_text=(
                state.saw_text_delta
                and assistant_message_has_tool_requests(event=event)
            ),
        ):
            if isinstance(stream_event, AssistantTextDeltaEvent):
                state.saw_text_delta = True
                state.output_parts.append(stream_event.text)
                continue

            if isinstance(stream_event, AssistantUsageEvent):
                if stream_event.prompt_tokens is not None:
                    state.prompt_tokens = stream_event.prompt_tokens
                if stream_event.completion_tokens is not None:
                    state.completion_tokens = stream_event.completion_tokens
                continue

            if isinstance(stream_event, ToolCallRequestedEvent):
                self._record_pending_tool_calls(
                    state=state,
                    tool_calls=(stream_event.tool_call,),
                )
                _logger.info(
                    'copilot_runtime_interactive_completion_tool_call',
                    tool_call_id=stream_event.tool_call.call_id,
                    tool_name=stream_event.tool_call.name,
                    pending_tool_call_count=len(state.pending_tool_calls),
                )
                continue

            if isinstance(stream_event, ToolCallsRequestedEvent):
                self._record_pending_tool_calls(
                    state=state,
                    tool_calls=stream_event.tool_calls,
                )
                _logger.info(
                    'copilot_runtime_interactive_completion_tool_calls',
                    tool_call_ids=[
                        tool_call.call_id for tool_call in stream_event.tool_calls
                    ],
                    tool_call_names=[
                        tool_call.name for tool_call in stream_event.tool_calls
                    ],
                    pending_tool_call_count=len(state.pending_tool_calls),
                )
                continue

            if isinstance(stream_event, AssistantTurnCompleteEvent):
                if stream_event.prompt_tokens is not None:
                    state.prompt_tokens = stream_event.prompt_tokens
                if stream_event.completion_tokens is not None:
                    state.completion_tokens = stream_event.completion_tokens
                _logger.info(
                    'copilot_runtime_interactive_completion_finished',
                    output_text_chars=len(''.join(state.output_parts)),
                    prompt_tokens=state.prompt_tokens,
                    completion_tokens=state.completion_tokens,
                )
                return True

        return False

    def _record_pending_tool_calls(
        self,
        *,
        state: _InteractiveCompletionState,
        tool_calls: Sequence[CanonicalToolCall],
    ) -> None:
        """Append new pending tool calls while deduplicating by tool-call id."""
        for tool_call in tool_calls:
            if tool_call.call_id in state.pending_tool_call_ids:
                continue
            state.pending_tool_call_ids.add(tool_call.call_id)
            state.pending_tool_calls.append(tool_call)

    def _should_send_interactive_continuation_prompt(
        self,
        *,
        event: SessionEvent,
        has_tool_results: bool,
        saw_visible_response: bool,
        continuation_prompt_sent: bool,
    ) -> bool:
        """Report whether a tool-result continuation needs a synthetic follow-up turn."""
        return (
            has_tool_results
            and not saw_visible_response
            and not continuation_prompt_sent
            and event.type
            in {
                SessionEventType.ASSISTANT_TURN_END,
                SessionEventType.SESSION_IDLE,
            }
        )

    def _build_sdk_tool_result(self, *, tool_result: CanonicalToolResult) -> ToolResult:
        """Convert one canonical tool result into the SDK tool-result payload."""
        return ToolResult(
            text_result_for_llm=tool_result.output_text,
            result_type='failure' if tool_result.is_error else 'success',
            error=tool_result.error_text,
            tool_telemetry={},
        )

    def _build_expired_session_tool_result(self) -> ToolResult:
        """Build the failure payload returned when a pending session has expired."""
        return ToolResult(
            text_result_for_llm='Provider session expired before the tool result arrived.',
            result_type='failure',
            error='provider session expired',
            tool_telemetry={},
        )

    async def _get_or_create_interactive_session(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> _InteractiveCopilotSession:
        """Reuse or create a persistent session for one tool-aware request."""
        if request.session_id is not None:
            async with self._interactive_sessions_lock:
                session_state = self._interactive_sessions.get(request.session_id)
            if session_state is None:
                raise ProviderError(
                    code='invalid_previous_response_id',
                    message='No pending provider session matched the supplied continuation id.',
                    status_code=400,
                )
            _logger.info(
                'copilot_runtime_interactive_session_reused',
                session_id=request.session_id,
                pending_tool_call_count=len(session_state.pending_tool_calls),
            )
            return session_state

        if route.runtime_model_id is None:
            raise ProviderError(
                code='runtime_route_invalid',
                message='Resolved route is missing a runtime model identifier.',
                status_code=500,
            )

        resolved_client = await self._get_client_for_request(request=request)
        await self._ensure_client_started(resolved_client.client)
        event_queue: asyncio.Queue[SessionEvent] = asyncio.Queue()
        session = await resolved_client.client.create_session(
            on_permission_request=self._deny_permission_request,
            on_event=event_queue.put_nowait,
            model=route.runtime_model_id,
            tools=self._build_tool_definitions(request=request) or None,
            excluded_tools=list(request.tool_routing_policy.excluded_builtin_tools)
            or None,
            working_directory=self._working_directory,
            streaming=True,
        )
        session_state = self._InteractiveCopilotSession(
            active_session=self._ActiveCopilotSession(
                session=session,
                client=resolved_client,
            ),
            event_queue=event_queue,
            pending_tool_calls={},
        )
        async with self._interactive_sessions_lock:
            self._interactive_sessions[session.session_id] = session_state
        _logger.info(
            'copilot_runtime_interactive_session_created',
            session_id=session.session_id,
            route_model_id=route.runtime_model_id,
            tool_definition_names=[tool.name for tool in request.tool_definitions],
            excluded_builtin_tools=list(
                request.tool_routing_policy.excluded_builtin_tools
            ),
            has_guidance=request.tool_routing_policy.guidance is not None,
        )
        await session.send(
            render_prompt(
                request=self._build_interactive_prompt_request(request=request)
            )
        )
        return session_state

    async def _submit_interactive_tool_results(
        self,
        *,
        session_id: str,
        tool_results: Sequence[CanonicalToolResult],
    ) -> None:
        """Deliver one or more northbound tool results into a pending SDK session."""
        async with self._interactive_sessions_lock:
            session_state = self._interactive_sessions.get(session_id)
            if session_state is None:
                raise ProviderError(
                    code='invalid_previous_response_id',
                    message='No pending provider session matched the supplied continuation id.',
                    status_code=400,
                )

            for result in tool_results:
                call_id = result.call_id
                pending_call = session_state.pending_tool_calls.get(call_id)
                submitted_result = self._build_sdk_tool_result(tool_result=result)
                if pending_call is None:
                    session_state.pending_tool_calls[call_id] = (
                        self._PendingToolCallState(
                            tool_call_id=call_id,
                            tool_name='',
                            arguments=None,
                            submitted_result=submitted_result,
                        )
                    )
                    continue

                if pending_call.future is not None and not pending_call.future.done():
                    pending_call.future.set_result(submitted_result)
                else:
                    pending_call.submitted_result = submitted_result
        _logger.info(
            'copilot_runtime_interactive_tool_results_submitted',
            session_id=session_id,
            tool_result_count=len(tool_results),
            tool_result_call_ids=[result.call_id for result in tool_results],
        )

    async def _wait_for_external_tool_result(
        self,
        invocation: ToolInvocation,
    ) -> ToolResult:
        """Wait for the northbound client to return the result for one tool call."""
        async with self._interactive_sessions_lock:
            session_state = self._interactive_sessions.get(invocation.session_id)
            if session_state is None:
                return self._build_expired_session_tool_result()

            pending_call = session_state.pending_tool_calls.get(invocation.tool_call_id)
            if pending_call is None:
                pending_call = self._PendingToolCallState(
                    tool_call_id=invocation.tool_call_id,
                    tool_name=invocation.tool_name,
                    arguments=invocation.arguments,
                )
                session_state.pending_tool_calls[invocation.tool_call_id] = pending_call

            if pending_call.submitted_result is not None:
                result = pending_call.submitted_result
                session_state.pending_tool_calls.pop(invocation.tool_call_id, None)
                return result

            if pending_call.future is None or pending_call.future.done():
                pending_call.future = asyncio.get_running_loop().create_future()
            future = pending_call.future

        try:
            return await future
        finally:
            async with self._interactive_sessions_lock:
                session_state = self._interactive_sessions.get(invocation.session_id)
                if session_state is not None:
                    session_state.pending_tool_calls.pop(invocation.tool_call_id, None)

    def _build_tool_definitions(self, *, request: CanonicalChatRequest) -> list[Tool]:
        """Convert canonical tool definitions into SDK tool registrations."""
        return [
            Tool(
                name=tool_definition.name,
                description=tool_definition.description,
                parameters=tool_definition.parameters,
                handler=self._wait_for_external_tool_result,
                overrides_built_in_tool=_should_override_built_in_tool(
                    tool_name=tool_definition.name
                ),
                skip_permission=True,
            )
            for tool_definition in request.tool_definitions
        ]

    def _build_interactive_prompt_request(
        self, *, request: CanonicalChatRequest
    ) -> CanonicalChatRequest:
        """Return the prompt payload used when starting a tool-aware SDK session."""
        guidance = request.tool_routing_policy.guidance
        if guidance is None:
            return request
        return request.model_copy(
            update={
                'messages': [
                    CanonicalChatMessage(
                        role='system',
                        content=guidance,
                    ),
                    *request.messages,
                ]
            }
        )

    async def _discard_interactive_session(
        self,
        *,
        session_id: str,
        disconnect: bool,
    ) -> None:
        """Remove a persistent session from the runtime and optionally disconnect it."""
        async with self._interactive_sessions_lock:
            session_state = self._interactive_sessions.pop(session_id, None)
        if session_state is None:
            return

        for pending_call in session_state.pending_tool_calls.values():
            if pending_call.future is not None and not pending_call.future.done():
                pending_call.future.set_result(
                    self._build_expired_session_tool_result()
                )

        _logger.info(
            'copilot_runtime_interactive_session_discarded',
            session_id=session_id,
            disconnect=disconnect,
            pending_tool_call_count=len(session_state.pending_tool_calls),
        )

        if not disconnect:
            return

        await self._close_session(active_session=session_state.active_session)


def _to_optional_int(value: int | float | str | None) -> int | None:
    """Convert SDK numeric fields into integers when values are present."""
    if value is None:
        return None

    return int(value)


def _should_override_built_in_tool(*, tool_name: str) -> bool:
    """Report whether one external tool should override an SDK built-in tool."""
    return tool_name == 'apply_patch'


def _summarize_canonical_request(*, request: CanonicalChatRequest) -> dict[str, object]:
    """Return a compact diagnostic summary for one runtime request."""
    return {
        'session_id': request.session_id,
        'message_count': len(request.messages),
        'message_roles': [message.role for message in request.messages],
        'tool_definition_count': len(request.tool_definitions),
        'tool_definition_names': [tool.name for tool in request.tool_definitions],
        'tool_result_count': len(request.tool_results),
        'tool_result_call_ids': [result.call_id for result in request.tool_results],
        'tool_routing_mode': request.tool_routing_policy.mode,
        'excluded_builtin_tools': list(
            request.tool_routing_policy.excluded_builtin_tools
        ),
        'has_guidance': request.tool_routing_policy.guidance is not None,
    }


def _normalize_runtime_models(
    *, models: Sequence[object]
) -> tuple[RuntimeDiscoveredModel, ...]:
    """Normalize and de-duplicate runtime-listed models while preserving order."""
    normalized_models: list[RuntimeDiscoveredModel] = []
    seen_model_ids: set[str] = set()
    for model in models:
        normalized_model = _normalize_runtime_model(model=model)
        if normalized_model is None or normalized_model.id in seen_model_ids:
            continue

        seen_model_ids.add(normalized_model.id)
        normalized_models.append(normalized_model)

    return tuple(normalized_models)


def _normalize_runtime_model(*, model: object) -> RuntimeDiscoveredModel | None:
    """Normalize one runtime-listed model into the provider discovery shape."""
    model_id = _to_optional_non_empty_string(getattr(model, 'id', None))
    if model_id is None:
        return None

    return RuntimeDiscoveredModel(
        id=model_id,
        copilot=_normalize_copilot_model_metadata(model=model),
    )


def _normalize_copilot_model_metadata(*, model: object) -> CopilotModelMetadata | None:
    """Normalize provider-owned metadata from one runtime-listed model object."""
    name = _to_optional_non_empty_string(getattr(model, 'name', None))
    capabilities = _normalize_copilot_model_capabilities(
        capabilities=getattr(model, 'capabilities', None)
    )
    policy = _normalize_copilot_model_policy(policy=getattr(model, 'policy', None))
    billing = _normalize_copilot_model_billing(billing=getattr(model, 'billing', None))
    supported_reasoning_efforts = _normalize_string_list(
        values=getattr(model, 'supported_reasoning_efforts', None)
    )
    default_reasoning_effort = _to_optional_non_empty_string(
        getattr(model, 'default_reasoning_effort', None)
    )
    if (
        name is None
        and capabilities is None
        and policy is None
        and billing is None
        and supported_reasoning_efforts is None
        and default_reasoning_effort is None
    ):
        return None

    return CopilotModelMetadata(
        name=name,
        capabilities=capabilities,
        policy=policy,
        billing=billing,
        supported_reasoning_efforts=supported_reasoning_efforts,
        default_reasoning_effort=default_reasoning_effort,
    )


def _normalize_copilot_model_capabilities(
    *, capabilities: object
) -> CopilotModelCapabilities | None:
    """Normalize runtime capability metadata into the provider metadata shape."""
    if capabilities is None:
        return None

    supports = _normalize_copilot_model_supports(
        supports=getattr(capabilities, 'supports', None)
    )
    limits = _normalize_copilot_model_limits(
        limits=getattr(capabilities, 'limits', None)
    )
    if supports is None and limits is None:
        return None

    return CopilotModelCapabilities(supports=supports, limits=limits)


def _normalize_copilot_model_supports(
    *, supports: object
) -> CopilotModelSupports | None:
    """Normalize runtime support flags into the provider metadata shape."""
    if supports is None:
        return None

    vision = _to_optional_bool(getattr(supports, 'vision', None))
    reasoning_effort = _to_optional_bool(getattr(supports, 'reasoning_effort', None))
    if vision is None and reasoning_effort is None:
        return None

    return CopilotModelSupports(
        vision=vision,
        reasoning_effort=reasoning_effort,
    )


def _normalize_copilot_model_limits(*, limits: object) -> CopilotModelLimits | None:
    """Normalize runtime limit metadata into the provider metadata shape."""
    if limits is None:
        return None

    max_prompt_tokens = _to_optional_non_negative_int(
        getattr(limits, 'max_prompt_tokens', None)
    )
    max_context_window_tokens = _to_optional_non_negative_int(
        getattr(limits, 'max_context_window_tokens', None)
    )
    vision = _normalize_copilot_model_vision_limits(
        vision_limits=getattr(limits, 'vision', None)
    )
    if (
        max_prompt_tokens is None
        and max_context_window_tokens is None
        and vision is None
    ):
        return None

    return CopilotModelLimits(
        max_prompt_tokens=max_prompt_tokens,
        max_context_window_tokens=max_context_window_tokens,
        vision=vision,
    )


def _normalize_copilot_model_vision_limits(
    *, vision_limits: object
) -> CopilotModelVisionLimits | None:
    """Normalize runtime vision limits into the provider metadata shape."""
    if vision_limits is None:
        return None

    supported_media_types = _normalize_string_list(
        values=getattr(vision_limits, 'supported_media_types', None)
    )
    max_prompt_images = _to_optional_non_negative_int(
        getattr(vision_limits, 'max_prompt_images', None)
    )
    max_prompt_image_size = _to_optional_non_negative_int(
        getattr(vision_limits, 'max_prompt_image_size', None)
    )
    if (
        supported_media_types is None
        and max_prompt_images is None
        and max_prompt_image_size is None
    ):
        return None

    return CopilotModelVisionLimits(
        supported_media_types=supported_media_types,
        max_prompt_images=max_prompt_images,
        max_prompt_image_size=max_prompt_image_size,
    )


def _normalize_copilot_model_policy(*, policy: object) -> CopilotModelPolicy | None:
    """Normalize runtime policy metadata into the provider metadata shape."""
    if policy is None:
        return None

    state = _to_optional_non_empty_string(getattr(policy, 'state', None))
    terms = _to_optional_non_empty_string(getattr(policy, 'terms', None))
    if state is None or terms is None:
        return None

    return CopilotModelPolicy(state=state, terms=terms)


def _normalize_copilot_model_billing(*, billing: object) -> CopilotModelBilling | None:
    """Normalize runtime billing metadata into the provider metadata shape."""
    if billing is None:
        return None

    multiplier = _to_optional_float(getattr(billing, 'multiplier', None))
    if multiplier is None:
        return None

    return CopilotModelBilling(multiplier=multiplier)


def _normalize_string_list(*, values: object) -> list[str] | None:
    """Return a cleaned string list when the runtime metadata supplies one."""
    if not isinstance(values, (list, tuple)):
        return None

    raw_values = cast('list[object] | tuple[object, ...]', values)
    normalized_values = [
        value.strip()
        for value in raw_values
        if isinstance(value, str) and value.strip()
    ]

    if not normalized_values:
        return None

    return normalized_values


def _to_optional_non_empty_string(value: object) -> str | None:
    """Return one stripped string when the runtime metadata supplies one."""
    if not isinstance(value, str):
        return None

    normalized_value = value.strip()
    if not normalized_value:
        return None

    return normalized_value


def _to_optional_bool(value: object) -> bool | None:
    """Return one boolean value when the runtime metadata supplies one."""
    return value if isinstance(value, bool) else None


def _to_optional_non_negative_int(value: object) -> int | None:
    """Return one non-negative integer when the runtime metadata supplies one."""
    if value is None or isinstance(value, bool):
        return None

    if not isinstance(value, int | float | str):
        return None

    try:
        normalized_value = int(value)
    except TypeError, ValueError:
        return None

    return normalized_value if normalized_value >= 0 else None


def _to_optional_float(value: object) -> float | None:
    """Return one float when the runtime metadata supplies one."""
    if value is None or isinstance(value, bool):
        return None

    if not isinstance(value, int | float | str):
        return None

    try:
        return float(value)
    except TypeError, ValueError:
        return None


def _build_runtime_completion(
    *,
    event: SessionEvent | None,
    session_id: str | None,
) -> RuntimeCompletion:
    """Translate a Copilot SDK session event into the runtime completion shape."""
    data = getattr(event, 'data', None)
    content = getattr(data, 'content', None)
    if event is None or not content:
        raise ProviderError(
            code='runtime_empty_response',
            message='Copilot runtime returned no assistant message content.',
            status_code=502,
        )

    try:
        prompt_tokens = _to_optional_int(getattr(data, 'input_tokens', None))
        completion_tokens = _to_optional_int(getattr(data, 'output_tokens', None))
    except (TypeError, ValueError) as error:
        raise ProviderError(
            code='runtime_invalid_response',
            message='Copilot runtime returned invalid token metadata.',
            status_code=502,
        ) from error

    return RuntimeCompletion(
        output_text=content,
        provider_response_id=getattr(data, 'message_id', None),
        session_id=session_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
