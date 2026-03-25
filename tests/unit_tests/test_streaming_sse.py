"""Unit tests for SSE encoding helpers used by the streaming transport slice."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from copilot_model_provider.streaming.events import (
    OpenAIChatCompletionChunk,
    OpenAIChatCompletionChunkChoice,
    OpenAIChatCompletionChunkDelta,
    StreamFinishReason,
)
from copilot_model_provider.streaming.sse import (
    encode_openai_chat_chunk,
    encode_openai_done_event,
    encode_sse_event,
    iter_openai_chat_sse,
    stream_openai_chat_sse,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def _build_chunk(
    *,
    content: str | None,
    finish_reason: StreamFinishReason | None = None,
) -> OpenAIChatCompletionChunk:
    """Construct a stable chat chunk used by SSE unit tests."""
    return OpenAIChatCompletionChunk(
        id='chatcmpl-stream-1',
        created=1_735_689_600,
        model='default',
        choices=[
            OpenAIChatCompletionChunkChoice(
                index=0,
                delta=OpenAIChatCompletionChunkDelta(
                    role='assistant' if content is not None else None,
                    content=content,
                ),
                finish_reason=finish_reason,
            )
        ],
    )


def test_encode_sse_event_splits_multiline_payloads() -> None:
    """Verify that multiline payloads are framed according to the SSE rules."""
    frame = encode_sse_event(data='line one\nline two', event='message', event_id='42')

    assert frame == 'event: message\nid: 42\ndata: line one\ndata: line two\n\n'


def test_encode_openai_chat_chunk_serializes_chunk_json() -> None:
    """Verify that chunk encoding emits the expected OpenAI JSON envelope."""
    frame = encode_openai_chat_chunk(chunk=_build_chunk(content='Hello'))

    assert frame.startswith('data: ')
    payload = json.loads(frame.removeprefix('data: ').strip())
    assert payload == {
        'id': 'chatcmpl-stream-1',
        'object': 'chat.completion.chunk',
        'created': 1735689600,
        'model': 'default',
        'choices': [
            {
                'index': 0,
                'delta': {'role': 'assistant', 'content': 'Hello'},
            }
        ],
    }


def test_iter_openai_chat_sse_appends_done_marker() -> None:
    """Verify that the synchronous SSE iterator appends the terminal marker."""
    frames = list(
        iter_openai_chat_sse(
            chunks=(
                _build_chunk(content='Hello'),
                _build_chunk(content=None, finish_reason='stop'),
            )
        )
    )

    assert len(frames) == 3
    assert frames[-1] == encode_openai_done_event()


async def _async_chunk_stream() -> AsyncIterator[OpenAIChatCompletionChunk]:
    """Yield a short deterministic chunk stream for async SSE testing."""
    yield _build_chunk(content='Hello')
    yield _build_chunk(content=None, finish_reason='stop')


@pytest.mark.asyncio
async def test_stream_openai_chat_sse_emits_async_frames_and_done_marker() -> None:
    """Verify that the async SSE iterator yields all chunk frames and ``[DONE]``."""
    frames = [
        frame async for frame in stream_openai_chat_sse(chunks=_async_chunk_stream())
    ]

    assert len(frames) == 3
    assert frames[0].startswith('data: ')
    assert frames[-1] == encode_openai_done_event()
