"""Shared HTTP helpers for the OpenAI-compatible API routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from copilot_model_provider.core.errors import ProviderError

if TYPE_CHECKING:
    from copilot.generated.session_events import SessionEvent
    from fastapi import FastAPI

    from copilot_model_provider.runtimes.base import RuntimeEventStream
    from copilot_model_provider.storage import SessionLockManager, SessionMap

from copilot.generated.session_events import SessionEventType


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


def resolve_session_map(app: FastAPI) -> SessionMap | None:
    """Return the configured session map stored on application state.

    Args:
        app: FastAPI application that owns the current request lifecycle.

    Returns:
        The configured session map when session-backed execution is enabled,
        otherwise ``None``.

    """
    return getattr(app.state, 'session_map', None)


def resolve_session_lock_manager(app: FastAPI) -> SessionLockManager | None:
    """Return the configured session lock manager stored on application state.

    Args:
        app: FastAPI application that owns the current request lifecycle.

    Returns:
        The configured session lock manager when session-backed execution is
        enabled, otherwise ``None``.

    """
    return getattr(app.state, 'session_lock_manager', None)


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
