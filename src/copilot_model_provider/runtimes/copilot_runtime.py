"""Copilot SDK-backed runtime for chat execution."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast, override

from copilot import CopilotClient, SubprocessConfig
from copilot.generated.session_events import (
    PermissionRequest,
    SessionEvent,
    SessionEventType,
)
from copilot.session import PermissionRequestResult

from copilot_model_provider.core.chat import render_prompt
from copilot_model_provider.core.errors import ProviderError
from copilot_model_provider.core.models import (
    CanonicalChatRequest,
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

if TYPE_CHECKING:
    from copilot.session import CopilotSession

PermissionRequestHandler = Callable[
    [PermissionRequest, dict[str, str]],
    PermissionRequestResult | Awaitable[PermissionRequestResult],
]


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

        client: CopilotClient
        stop_on_close: bool = False

    @dataclass(frozen=True, slots=True)
    class _ActiveCopilotSession:
        """Opened Copilot session plus the client lifecycle policy that owns it."""

        session: CopilotSession
        client: CopilotRuntime._ResolvedCopilotClient

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


def _to_optional_int(value: int | float | str | None) -> int | None:
    """Convert SDK numeric fields into integers when values are present."""
    if value is None:
        return None

    return int(value)


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
