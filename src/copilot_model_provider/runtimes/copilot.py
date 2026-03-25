"""Copilot SDK-backed runtime adapter for chat execution."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Protocol, cast, override

from copilot import CopilotClient, PermissionRequestResult
from copilot.generated.session_events import (
    PermissionRequest,
    PermissionRequestKind,
    SessionEvent,
    SessionEventType,
)

from copilot_model_provider.core.chat import render_prompt
from copilot_model_provider.core.errors import ProviderError
from copilot_model_provider.core.models import (
    CanonicalChatRequest,
    ResolvedRoute,
    RuntimeCompletion,
    RuntimeHealth,
)
from copilot_model_provider.core.policies import PermissionDecision, PolicyEngine
from copilot_model_provider.runtimes.base import RuntimeAdapter, RuntimeEventStream
from copilot_model_provider.tools import MCPRegistry, ToolRegistry

if TYPE_CHECKING:
    from typing import Literal


class CopilotSessionLike(Protocol):
    """Typed subset of the Copilot session API used by this adapter."""

    session_id: str

    async def send(
        self,
        prompt: str,
        *,
        attachments: list[object] | None = None,
        mode: Literal['enqueue', 'immediate'] | None = None,
    ) -> str:
        """Send a prompt without waiting for session completion."""
        ...

    async def send_and_wait(
        self,
        prompt: str,
        *,
        attachments: list[object] | None = None,
        mode: Literal['enqueue', 'immediate'] | None = None,
        timeout: float = 60.0,  # noqa: ASYNC109 - mirrors SDK signature
    ) -> SessionEvent | None:
        """Send a prompt and wait for the final assistant message."""
        ...

    def on(self, handler: Callable[[SessionEvent], None]) -> Callable[[], None]:
        """Subscribe to session events and return an unsubscribe callback."""
        ...

    async def disconnect(self) -> None:
        """Disconnect local runtime resources without deleting the session."""
        ...

    async def destroy(self) -> None:
        """Tear down the session and release associated runtime resources."""
        ...


PermissionRequestHandler = Callable[
    [PermissionRequest, dict[str, str]],
    PermissionRequestResult | Awaitable[PermissionRequestResult],
]


class CopilotClientLike(Protocol):
    """Typed subset of the Copilot client API used by this adapter."""

    def get_state(self) -> str:
        """Return the current client lifecycle state."""
        ...

    def start(self) -> None:
        """Start the underlying Copilot client when it is disconnected."""
        ...

    async def create_session(
        self,
        *,
        on_permission_request: PermissionRequestHandler,
        model: str | None = None,
        session_id: str | None = None,
        working_directory: str | None = None,
        streaming: bool | None = None,
        tools: tuple[object, ...] | None = None,
        mcp_servers: Mapping[str, object] | None = None,
        on_event: Callable[[SessionEvent], None] | None = None,
    ) -> CopilotSessionLike:
        """Create an ephemeral session used for one chat-completion request."""
        ...

    async def resume_session(
        self,
        session_id: str,
        *,
        on_permission_request: PermissionRequestHandler,
        model: str | None = None,
        working_directory: str | None = None,
        streaming: bool | None = None,
        tools: tuple[object, ...] | None = None,
        mcp_servers: Mapping[str, object] | None = None,
        on_event: Callable[[SessionEvent], None] | None = None,
    ) -> CopilotSessionLike:
        """Resume an existing session for a follow-up request."""
        ...


class CopilotRuntimeAdapter(RuntimeAdapter):
    """Execute stateless chat completions through the installed Copilot SDK."""

    def __init__(
        self,
        *,
        client_factory: Callable[[], CopilotClientLike] | None = None,
        timeout_seconds: float = 60.0,
        working_directory: str | None = None,
        tool_registry: ToolRegistry | None = None,
        policy_engine: PolicyEngine | None = None,
        mcp_registry: MCPRegistry | None = None,
    ) -> None:
        """Initialize the adapter with lazy Copilot client construction.

        Args:
            client_factory: Optional factory used to construct the underlying
                Copilot client. Tests can override this with a fake SDK surface.
            timeout_seconds: Maximum wall-clock time to wait for a non-streaming
                assistant response.
            working_directory: Optional working directory forwarded into new
                ephemeral Copilot sessions.
            tool_registry: Registry of provider-known tools used by later
                permission and session wiring.
            policy_engine: Policy engine that decides whether runtime tool
                permission requests can be approved automatically.
            mcp_registry: Registry of MCP servers forwarded into new and resumed
                Copilot sessions.

        """
        super().__init__(runtime_name='copilot')
        self._client_factory = client_factory or self._build_default_client
        self._timeout_seconds = timeout_seconds
        self._working_directory = working_directory
        self._tool_registry = tool_registry or ToolRegistry()
        self._policy_engine = policy_engine or PolicyEngine(
            tool_registry=self._tool_registry,
            mcp_registry=mcp_registry,
        )
        self._mcp_registry = mcp_registry or MCPRegistry()
        self._client: CopilotClientLike | None = None

    @override
    def default_route(self) -> ResolvedRoute:
        """Return the default route for the Copilot-backed runtime."""
        return ResolvedRoute(runtime=self.runtime_name, session_mode='stateless')

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
    async def complete_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeCompletion:
        """Execute a canonical chat request through an ephemeral Copilot session.

        Args:
            request: The canonical stateless chat request to execute.
            route: The resolved model routing metadata.

        Returns:
            A normalized runtime completion built from the final assistant
            message event returned by the Copilot SDK.

        Raises:
            ProviderError: If routing metadata is incomplete, the Copilot SDK
                fails, or no final assistant message is returned.

        """
        if route.runtime_model_id is None:
            raise ProviderError(
                code='runtime_route_invalid',
                message='Resolved route is missing a runtime model identifier.',
                status_code=500,
            )

        session = await self._open_session(
            route=route,
            session_id=request.session_id,
            streaming=False,
        )
        try:
            event = await session.send_and_wait(
                render_prompt(request=request),
                timeout=self._timeout_seconds,
            )
            return _build_runtime_completion(
                event=event,
                session_id=session.session_id,
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
            await self._close_session(
                session=session,
                execution_mode=request.execution_mode,
            )

    @override
    async def stream_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeEventStream:
        """Execute a canonical streaming chat request through the Copilot SDK.

        Args:
            request: The canonical streaming request to execute.
            route: The resolved model routing metadata.

        Returns:
            Runtime-owned session metadata and an async stream of Copilot SDK
            events emitted for the requested assistant turn.

        Raises:
            ProviderError: If routing metadata is incomplete or the Copilot SDK
                fails while preparing the streaming session.

        """
        session = await self._open_session(
            route=route,
            session_id=request.session_id,
            streaming=True,
        )
        session_closed = False

        async def _finalize_session() -> None:
            """Close the Copilot session at most once."""
            nonlocal session_closed
            if session_closed:
                return

            session_closed = True
            await self._close_session(
                session=session,
                execution_mode=request.execution_mode,
            )

        async def _event_stream() -> AsyncIterator[SessionEvent]:
            """Yield SDK events for one assistant turn and close the session cleanly."""
            queue: asyncio.Queue[SessionEvent] = asyncio.Queue()

            def _handle_event(event: SessionEvent) -> None:
                queue.put_nowait(event)

            unsubscribe = session.on(_handle_event)
            try:
                await session.send(render_prompt(request=request))
                while True:
                    try:
                        event = await asyncio.wait_for(
                            queue.get(),
                            timeout=self._timeout_seconds,
                        )
                    except TimeoutError as error:
                        raise ProviderError(
                            code='runtime_timeout',
                            message=(
                                'Timed out while waiting for Copilot streaming events.'
                            ),
                            status_code=504,
                        ) from error

                    yield event
                    if event.type in {
                        SessionEventType.ASSISTANT_TURN_END,
                        SessionEventType.SESSION_ERROR,
                        SessionEventType.SESSION_IDLE,
                    }:
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
            session_id=session.session_id,
            events=_event_stream(),
            close=_finalize_session,
        )

    def _get_or_create_client(self) -> CopilotClientLike:
        """Build the lazy Copilot client on first use and cache it afterwards."""
        if self._client is None:
            self._client = self._client_factory()

        return self._client

    def _ensure_client_started(self, client: CopilotClientLike) -> None:
        """Start the Copilot client when the lazy adapter has not connected yet.

        Args:
            client: The underlying Copilot client instance used by this adapter.

        Raises:
            ProviderError: If the client reports an error state before execution.

        """
        state = client.get_state()
        if state == 'error':
            raise ProviderError(
                code='runtime_unhealthy',
                message='Copilot client is in an error state.',
                status_code=503,
            )

        if state == 'disconnected':
            client.start()

    async def _open_session(
        self,
        *,
        route: ResolvedRoute,
        session_id: str | None,
        streaming: bool,
    ) -> CopilotSessionLike:
        """Open or resume a Copilot session for one request.

        Args:
            route: Resolved model routing metadata for the request.
            session_id: Existing Copilot session identifier to resume, when any.
            streaming: Whether the returned session should emit streaming events.

        Returns:
            A connected Copilot session ready for message execution.

        Raises:
            ProviderError: If routing metadata is incomplete.

        """
        if route.runtime_model_id is None:
            raise ProviderError(
                code='runtime_route_invalid',
                message='Resolved route is missing a runtime model identifier.',
                status_code=500,
            )

        client = self._get_or_create_client()
        self._ensure_client_started(client)
        tools = self._tool_registry.sdk_tools() or None
        mcp_servers = self._mcp_registry.sdk_server_configs() or None
        if session_id is not None:
            return await client.resume_session(
                session_id,
                on_permission_request=self._handle_permission_request,
                model=route.runtime_model_id,
                working_directory=self._working_directory,
                streaming=streaming,
                tools=tools,
                mcp_servers=mcp_servers,
            )

        return await client.create_session(
            on_permission_request=self._handle_permission_request,
            model=route.runtime_model_id,
            working_directory=self._working_directory,
            streaming=streaming,
            tools=tools,
            mcp_servers=mcp_servers,
        )

    async def _close_session(
        self,
        *,
        session: CopilotSessionLike,
        execution_mode: str,
    ) -> None:
        """Close a Copilot session according to the request execution mode."""
        if execution_mode == 'sessional':
            await session.disconnect()
            return

        await session.destroy()

    @staticmethod
    def _build_default_client() -> CopilotClientLike:
        """Construct the default lazy Copilot client for production usage."""
        return cast('CopilotClientLike', CopilotClient(auto_start=False))

    def _handle_permission_request(
        self,
        request: PermissionRequest,
        context: dict[str, str],
    ) -> PermissionRequestResult:
        """Return a policy-driven decision for one SDK permission request.

        Args:
            request: Permission request emitted by the Copilot SDK.
            context: Additional SDK context describing the pending approval.

        Returns:
            A ``PermissionRequestResult`` that either approves a known safe tool
            request or denies the request with a deterministic policy reason.

        """
        decision = _evaluate_permission_request(
            request=request,
            context=context,
            policy_engine=self._policy_engine,
        )
        if decision.allowed:
            return PermissionRequestResult(kind='approved', message=decision.reason)

        return PermissionRequestResult(kind='denied-by-rules', message=decision.reason)


def _evaluate_permission_request(
    request: PermissionRequest,
    context: dict[str, str],
    *,
    policy_engine: PolicyEngine,
) -> PermissionDecision:
    """Evaluate one SDK permission request against the configured policy engine.

    Args:
        request: The permission request emitted by the Copilot SDK.
        context: Additional request-scoped context from the SDK.
        policy_engine: Policy evaluator used to approve or deny tool requests.

    Returns:
        A normalized ``PermissionDecision`` describing whether the request
        should be approved automatically.

    """
    del context
    if request.kind == PermissionRequestKind.MCP:
        if request.server_name is None:
            return PermissionDecision(
                allowed=False,
                reason='permission request does not include an MCP server name',
            )

        return policy_engine.evaluate_mcp_server_permission(request.server_name)

    tool_name = _resolve_permission_tool_name(request=request)
    if tool_name is None:
        return PermissionDecision(
            allowed=False,
            reason='permission request does not map to an approved tool name',
        )

    return policy_engine.evaluate_tool_permission(
        tool_name,
        is_builtin=request.kind != PermissionRequestKind.CUSTOM_TOOL,
    )


def _resolve_permission_tool_name(*, request: PermissionRequest) -> str | None:
    """Resolve the most specific tool-like identifier from a permission request."""
    if request.tool_name:
        return request.tool_name

    return None


def _to_optional_int(value: int | float | str | None) -> int | None:
    """Convert SDK numeric fields into integers when values are present."""
    if value is None:
        return None

    return int(value)


def _build_runtime_completion(
    *,
    event: SessionEvent | None,
    session_id: str | None,
) -> RuntimeCompletion:
    """Translate a Copilot SDK session event into the runtime completion shape.

    Args:
        event: The final assistant-message event returned by ``send_and_wait``.
        session_id: The active Copilot session identifier associated with the
            completed assistant turn.

    Returns:
        A normalized ``RuntimeCompletion`` ready for HTTP response translation.

    Raises:
        ProviderError: If the SDK returns no assistant content or malformed token
            metadata.

    """
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
