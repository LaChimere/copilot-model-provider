"""Copilot SDK-backed runtime adapter for chat execution."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, Protocol, cast, override

from copilot import CopilotClient, PermissionRequestResult, SubprocessConfig
from copilot.generated.session_events import (
    PermissionRequest,
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
from copilot_model_provider.runtimes.base import RuntimeAdapter, RuntimeEventStream


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

    async def start(self) -> None:
        """Start the underlying Copilot client when it is disconnected."""
        ...

    async def stop(self) -> None:
        """Stop the underlying Copilot client and release runtime resources."""
        ...

    async def create_session(
        self,
        *,
        on_permission_request: PermissionRequestHandler,
        model: str | None = None,
        working_directory: str | None = None,
        streaming: bool | None = None,
        on_event: Callable[[SessionEvent], None] | None = None,
    ) -> CopilotSessionLike:
        """Create an ephemeral session used for one chat-completion request."""
        ...


class CopilotRuntimeAdapter(RuntimeAdapter):
    """Execute stateless chat completions through the installed Copilot SDK."""

    def __init__(
        self,
        *,
        client_factory: Callable[[], CopilotClientLike] | None = None,
        authenticated_client_factory: Callable[[str], CopilotClientLike] | None = None,
        timeout_seconds: float = 60.0,
        working_directory: str | None = None,
    ) -> None:
        """Initialize the adapter with lazy Copilot client construction.

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
        super().__init__(runtime_name='copilot')
        self._client_factory = client_factory or self._build_default_client
        self._authenticated_client_factory = (
            authenticated_client_factory or self._build_authenticated_client
        )
        self._timeout_seconds = timeout_seconds
        self._working_directory = working_directory
        self._client: CopilotClientLike | None = None

    @property
    def connection_mode(self) -> str:
        """Report the runtime connection mode used by the adapter."""
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
    async def complete_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeCompletion:
        """Execute a canonical chat request through an ephemeral Copilot session."""
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
        try:
            event = await active_session.session.send_and_wait(
                render_prompt(request=request),
                timeout=self._timeout_seconds,
            )
            return _build_runtime_completion(
                event=event,
                session_id=active_session.session.session_id,
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

    @override
    async def stream_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeEventStream:
        """Execute a canonical streaming chat request through the Copilot SDK."""
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

        client: CopilotClientLike
        stop_on_close: bool = False

    @dataclass(frozen=True, slots=True)
    class _ActiveCopilotSession:
        """Opened Copilot session plus the client lifecycle policy that owns it."""

        session: CopilotSessionLike
        client: CopilotRuntimeAdapter._ResolvedCopilotClient

    def _get_or_create_client(self) -> CopilotClientLike:
        """Build the lazy Copilot client on first use and cache it afterwards."""
        if self._client is None:
            self._client = self._client_factory()

        return self._client

    async def _ensure_client_started(self, client: CopilotClientLike) -> None:
        """Start the Copilot client when the lazy adapter has not connected yet."""
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
        return self._ActiveCopilotSession(
            session=await resolved_client.client.create_session(
                on_permission_request=self._deny_permission_request,
                model=route.runtime_model_id,
                working_directory=self._working_directory,
                streaming=streaming,
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
        if request.runtime_auth_token is None:
            return self._ResolvedCopilotClient(client=self._get_or_create_client())

        return self._ResolvedCopilotClient(
            client=self._authenticated_client_factory(request.runtime_auth_token),
            stop_on_close=True,
        )

    async def _stop_client(self, client: CopilotClientLike) -> None:
        """Stop a short-lived Copilot client once its request-scoped work is done."""
        await client.stop()

    def _build_default_client(self) -> CopilotClientLike:
        """Construct the default lazy Copilot client for production usage."""
        return cast('CopilotClientLike', CopilotClient(None, auto_start=False))

    def _build_authenticated_client(self, github_token: str) -> CopilotClientLike:
        """Construct a subprocess-backed Copilot client for one bearer token.

        Args:
            github_token: Request-scoped GitHub bearer token used for Copilot auth.

        Returns:
            A ``CopilotClientLike`` configured to spawn its own CLI subprocess
            with the provided GitHub token injected through SDK auth settings.

        """
        return cast(
            'CopilotClientLike',
            CopilotClient(
                SubprocessConfig(
                    cwd=self._working_directory,
                    github_token=github_token,
                ),
                auto_start=False,
            ),
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
