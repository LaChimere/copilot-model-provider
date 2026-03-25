"""Smoke tests for the async SSE stream owned by the streaming transport slice."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from copilot_model_provider.streaming.sse import stream_openai_chat_sse
from copilot_model_provider.streaming.translators import (
    build_finish_chunk,
    build_text_delta_chunk,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from copilot_model_provider.streaming.events import OpenAIChatCompletionChunk


async def _chunk_stream() -> AsyncIterator[OpenAIChatCompletionChunk]:
    """Yield a minimal assistant stream for smoke-testing the async encoder."""
    yield build_text_delta_chunk(
        completion_id='chatcmpl-stream-1',
        model='default',
        text='Smoke',
        role='assistant',
        created=1_735_689_600,
    )
    yield build_finish_chunk(
        completion_id='chatcmpl-stream-1',
        model='default',
        created=1_735_689_600,
    )


@pytest.mark.asyncio
async def test_streaming_smoke_async_encoder_produces_done_terminated_frames() -> None:
    """Verify that the async SSE encoder emits frames in the expected order."""
    frames = [frame async for frame in stream_openai_chat_sse(chunks=_chunk_stream())]

    assert len(frames) == 3
    assert '"object":"chat.completion.chunk"' in frames[0]
    assert frames[-1] == 'data: [DONE]\n\n'
