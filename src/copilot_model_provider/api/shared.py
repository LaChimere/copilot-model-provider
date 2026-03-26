"""Shared HTTP helpers for the OpenAI-compatible API routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from copilot.generated.session_events import SessionEventType

from copilot_model_provider.core.errors import ProviderError
from copilot_model_provider.streaming.events import AssistantTextDeltaEvent
from copilot_model_provider.streaming.translators import translate_session_event

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from copilot.generated.session_events import SessionEvent

    from copilot_model_provider.core.models import CanonicalChatRequest, ResolvedRoute
    from copilot_model_provider.runtimes.protocols import (
        RuntimeEventStream,
        RuntimeProtocol,
    )
    from copilot_model_provider.streaming.events import CanonicalStreamingEvent


async def open_runtime_event_stream(
    *,
    runtime: RuntimeProtocol,
    request: CanonicalChatRequest,
    route: ResolvedRoute,
) -> RuntimeEventStream:
    """Open a runtime-owned streaming session for one canonical request.

    Args:
        runtime: Runtime implementation that owns the streaming execution path.
        request: Canonical request that should execute through the runtime.
        route: Resolved runtime target for the current request.

    Returns:
        A ``RuntimeEventStream`` ready to be consumed by an HTTP streaming route.

    """
    return await runtime.stream_chat(request=request, route=route)


async def iter_canonical_runtime_stream_events(
    *,
    runtime_stream: RuntimeEventStream,
) -> AsyncIterator[CanonicalStreamingEvent]:
    """Yield canonical stream events with shared de-duplication behavior.

    Args:
        runtime_stream: Runtime-owned event stream returned by the active runtime.

    Yields:
        Canonical stream events that are relevant to the northbound transport.

    """
    saw_text_delta = False
    async for event in runtime_stream.events:
        if should_skip_aggregated_assistant_message(
            event=event,
            saw_text_delta=saw_text_delta,
        ):
            continue

        stream_event = translate_session_event(event=event)
        if stream_event is None:
            continue

        if isinstance(stream_event, AssistantTextDeltaEvent):
            saw_text_delta = True

        yield stream_event


def normalize_optional_header_value(*, value: str | None) -> str | None:
    """Normalize optional header values so blank strings behave like ``None``.

    Args:
        value: Raw HTTP header value received from the client.

    Returns:
        The stripped header value when it contains non-whitespace text;
        otherwise ``None``.

    """
    if value is None:
        return None

    normalized_value = value.strip()
    return normalized_value or None


def normalize_bearer_token(*, value: str | None) -> str | None:
    """Normalize a bearer-token Authorization header for runtime passthrough.

    Args:
        value: Raw ``Authorization`` header value from the HTTP request.

    Returns:
        The stripped bearer token, or ``None`` when the header is absent.

    Raises:
        ProviderError: If the Authorization header is present but does not use
            the ``Bearer <token>`` format.

    """
    normalized_value = normalize_optional_header_value(value=value)
    if normalized_value is None:
        return None

    scheme, _, token = normalized_value.partition(' ')
    normalized_token = token.strip()
    if scheme.lower() != 'bearer' or not normalized_token:
        raise ProviderError(
            code='invalid_authorization_header',
            message='Authorization header must use the Bearer token format.',
            status_code=400,
        )

    return normalized_token


def resolve_runtime_auth_token(
    *,
    authorization_header: str | None,
    default_token: str | None,
) -> str | None:
    """Resolve the runtime auth token for one incoming request.

    Args:
        authorization_header: Raw ``Authorization`` header supplied by the client.
        default_token: Optional service-level fallback token, typically injected
            into the running container environment.

    Returns:
        The request-scoped bearer token when the header is present, otherwise the
        normalized fallback token when configured, otherwise ``None``.

    Raises:
        ProviderError: If the client supplied an ``Authorization`` header that is
            present but not in ``Bearer <token>`` format.

    """
    request_token = normalize_bearer_token(value=authorization_header)
    if request_token is not None:
        return request_token

    return normalize_optional_header_value(value=default_token)


async def close_runtime_event_stream(*, runtime_stream: RuntimeEventStream) -> None:
    """Close a runtime event stream before the HTTP response starts consuming it.

    Args:
        runtime_stream: Runtime-owned event stream metadata that may expose an
            explicit cleanup callback or an ``aclose`` coroutine on the event
            iterator itself.

    """
    if runtime_stream.close is not None:
        await runtime_stream.close()
        return

    aclose = getattr(runtime_stream.events, 'aclose', None)
    if aclose is not None:
        await aclose()


def should_skip_aggregated_assistant_message(
    *,
    event: SessionEvent,
    saw_text_delta: bool,
) -> bool:
    """Report whether a streaming route should ignore an aggregated assistant message.

    The Copilot runtime may emit token/text delta events during streaming and then
    later emit a full ``assistant.message`` event containing the already-assembled
    text. Northbound OpenAI-compatible streaming routes should not replay that
    aggregate message after they have already emitted deltas, or clients such as
    Codex will display duplicate text.

    Args:
        event: Raw Copilot SDK session event currently being processed.
        saw_text_delta: Whether the route has already emitted at least one text
            delta for the current assistant turn.

    Returns:
        ``True`` when the event is an aggregated ``assistant.message`` that would
        duplicate previously emitted delta text, otherwise ``False``.

    """
    return saw_text_delta and event.type == SessionEventType.ASSISTANT_MESSAGE
