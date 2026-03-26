"""Streaming helpers for OpenAI Responses-compatible SSE transport."""

from __future__ import annotations

import json

from copilot_model_provider.streaming.sse import encode_sse_event


def encode_openai_responses_event(*, payload: str) -> str:
    """Encode one serialized Responses streaming payload into an SSE frame.

    Args:
        payload: JSON-serialized event payload to emit.

    Returns:
        An SSE message compatible with OpenAI-style Responses streaming.

    """
    return encode_sse_event(data=payload)


def encode_openai_responses_error_event(*, code: str, message: str) -> str:
    """Encode a minimal Responses-compatible stream error event.

    Args:
        code: Stable machine-readable error code.
        message: Human-readable error message for the client.

    Returns:
        An SSE message containing a minimal ``error`` event payload.

    """
    return encode_openai_responses_event(
        payload=json.dumps(
            {
                'type': 'error',
                'code': code,
                'message': message,
            }
        )
    )
