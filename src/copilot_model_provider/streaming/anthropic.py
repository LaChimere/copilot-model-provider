"""Streaming helpers for Anthropic-compatible SSE transport."""

from __future__ import annotations

import json

from copilot_model_provider.core.errors import (
    AnthropicErrorDetail,
    AnthropicErrorResponse,
    AnthropicErrorType,
)
from copilot_model_provider.streaming.sse import encode_sse_event


def encode_anthropic_event(*, event: str, payload: str) -> str:
    """Encode one Anthropic-compatible SSE event."""
    return encode_sse_event(event=event, data=payload)


def encode_anthropic_error_event(*, message: str) -> str:
    """Encode a minimal Anthropic-compatible error SSE event."""
    payload = AnthropicErrorResponse(
        error=AnthropicErrorDetail(type=AnthropicErrorType.API, message=message)
    )
    return encode_anthropic_event(
        event='error',
        payload=json.dumps(payload.model_dump(mode='json')),
    )
