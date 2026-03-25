"""Copilot SDK-backed runtime adapter for non-streaming chat execution."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Protocol, cast, override

from copilot import CopilotClient, PermissionRequestResult
from copilot.generated.session_events import PermissionRequest, SessionEvent

from copilot_model_provider.core.chat import render_prompt
from copilot_model_provider.core.errors import ProviderError
from copilot_model_provider.core.models import (
    CanonicalChatRequest,
    ResolvedRoute,
    RuntimeCompletion,
    RuntimeHealth,
)
from copilot_model_provider.runtimes.base import RuntimeAdapter

if TYPE_CHECKING:
    from typing import Literal


class CopilotSessionLike(Protocol):
    """Typed subset of the Copilot session API used by this adapter."""

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

    def destroy(self) -> None:
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

    def create_session(
        self,
        *,
        on_permission_request: PermissionRequestHandler,
        model: str | None = None,
        working_directory: str | None = None,
        streaming: bool | None = None,
    ) -> CopilotSessionLike:
        """Create an ephemeral session used for one chat-completion request."""
        ...


class CopilotRuntimeAdapter(RuntimeAdapter):
    """Execute stateless chat completions through the installed Copilot SDK."""

    def __init__(
        self,
        *,
        client_factory: Callable[[], CopilotClientLike] | None = None,
        timeout_seconds: float = 60.0,
        working_directory: str | None = None,
    ) -> None:
        """Initialize the adapter with lazy Copilot client construction.

        Args:
            client_factory: Optional factory used to construct the underlying
                Copilot client. Tests can override this with a fake SDK surface.
            timeout_seconds: Maximum wall-clock time to wait for a non-streaming
                assistant response.
            working_directory: Optional working directory forwarded into new
                ephemeral Copilot sessions.

        """
        super().__init__(runtime_name='copilot')
        self._client_factory = client_factory or self._build_default_client
        self._timeout_seconds = timeout_seconds
        self._working_directory = working_directory
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

        client = self._get_or_create_client()
        self._ensure_client_started(client)
        session = client.create_session(
            on_permission_request=_deny_permission_requests,
            model=route.runtime_model_id,
            working_directory=self._working_directory,
            streaming=False,
        )
        try:
            event = await session.send_and_wait(
                render_prompt(request=request),
                timeout=self._timeout_seconds,
            )
            return _build_runtime_completion(event=event)
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
            session.destroy()

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

    @staticmethod
    def _build_default_client() -> CopilotClientLike:
        """Construct the default lazy Copilot client for production usage."""
        return cast('CopilotClientLike', CopilotClient(auto_start=False))


def _deny_permission_requests(
    request: PermissionRequest,
    context: dict[str, str],
) -> PermissionRequestResult:
    """Return a deterministic denial for interactive permission requests.

    Args:
        request: The permission request emitted by the Copilot SDK.
        context: Additional request-scoped context from the SDK.

    Returns:
        A ``PermissionRequestResult`` that explicitly denies interactive
        approvals because this compatibility layer is serving plain HTTP calls.

    """
    del request, context
    return PermissionRequestResult(
        kind='denied-no-approval-rule-and-could-not-request-from-user',
        message='Interactive permission requests are not supported by this API.',
    )


def _to_optional_int(value: int | float | str | None) -> int | None:
    """Convert SDK numeric fields into integers when values are present."""
    if value is None:
        return None

    return int(value)


def _build_runtime_completion(*, event: SessionEvent | None) -> RuntimeCompletion:
    """Translate a Copilot SDK session event into the runtime completion shape.

    Args:
        event: The final assistant-message event returned by ``send_and_wait``.

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
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
