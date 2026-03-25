"""Server-Sent Events encoders for OpenAI-compatible chat streaming."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterable, AsyncIterator, Iterable, Iterator

    from copilot_model_provider.streaming.events import OpenAIChatCompletionChunk


def encode_sse_event(
    *,
    data: str,
    event: str | None = None,
    event_id: str | None = None,
) -> str:
    """Encode a single Server-Sent Events message.

    Args:
        data: The event payload to emit. Multiline payloads are split into one
            ``data:`` line per line to follow the SSE framing rules.
        event: Optional event name emitted before the payload.
        event_id: Optional event identifier emitted before the payload.

    Returns:
        A fully framed SSE message that ends with a blank line.

    """
    lines: list[str] = []
    if event is not None:
        lines.append(f'event: {event}')
    if event_id is not None:
        lines.append(f'id: {event_id}')

    payload_lines = data.splitlines() or ['']
    lines.extend(f'data: {line}' for line in payload_lines)
    return '\n'.join(lines) + '\n\n'


def encode_openai_chat_chunk(*, chunk: OpenAIChatCompletionChunk) -> str:
    """Encode an OpenAI-compatible chat chunk into an SSE data frame.

    Args:
        chunk: The OpenAI-compatible chunk to serialize.

    Returns:
        An SSE message containing the chunk JSON payload.

    """
    return encode_sse_event(data=chunk.model_dump_json(exclude_none=True))


def encode_openai_done_event() -> str:
    """Encode the terminal OpenAI ``[DONE]`` marker as an SSE message.

    Returns:
        The SSE-framed terminal marker expected by OpenAI-compatible clients.

    """
    return encode_sse_event(data='[DONE]')


def iter_openai_chat_sse(
    *,
    chunks: Iterable[OpenAIChatCompletionChunk],
    include_done: bool = True,
) -> Iterator[str]:
    """Encode a chunk iterable into SSE frames.

    Args:
        chunks: Ordered chat chunks that should be emitted to the client.
        include_done: Whether to append the terminal ``[DONE]`` marker.

    Yields:
        SSE-encoded frames in the same order as the provided chunks.

    """
    for chunk in chunks:
        yield encode_openai_chat_chunk(chunk=chunk)

    if include_done:
        yield encode_openai_done_event()


async def stream_openai_chat_sse(
    *,
    chunks: AsyncIterable[OpenAIChatCompletionChunk],
    include_done: bool = True,
) -> AsyncIterator[str]:
    """Asynchronously encode a chunk stream into SSE frames.

    Args:
        chunks: Async stream of OpenAI-compatible chat chunks.
        include_done: Whether to append the terminal ``[DONE]`` marker.

    Yields:
        SSE-encoded frames suitable for ``StreamingResponse`` integration.

    """
    async for chunk in chunks:
        yield encode_openai_chat_chunk(chunk=chunk)

    if include_done:
        yield encode_openai_done_event()
