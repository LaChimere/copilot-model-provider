"""Streaming transport helpers for future OpenAI-compatible convergence."""

from copilot_model_provider.streaming.events import (
    AssistantTextDeltaEvent,
    AssistantTurnCompleteEvent,
    CanonicalStreamingEvent,
    OpenAIChatCompletionChunk,
    OpenAIChatCompletionChunkChoice,
    OpenAIChatCompletionChunkDelta,
    StreamFinishReason,
    StreamingErrorEvent,
)
from copilot_model_provider.streaming.sse import (
    encode_openai_chat_chunk,
    encode_openai_done_event,
    encode_sse_event,
    iter_openai_chat_sse,
    stream_openai_chat_sse,
)
from copilot_model_provider.streaming.translators import (
    build_finish_chunk,
    build_text_delta_chunk,
    translate_session_event,
    translate_session_event_to_openai_chunks,
    translate_stream_event_to_openai_chunks,
)

__all__ = [
    'AssistantTextDeltaEvent',
    'AssistantTurnCompleteEvent',
    'CanonicalStreamingEvent',
    'OpenAIChatCompletionChunk',
    'OpenAIChatCompletionChunkChoice',
    'OpenAIChatCompletionChunkDelta',
    'StreamFinishReason',
    'StreamingErrorEvent',
    'build_finish_chunk',
    'build_text_delta_chunk',
    'encode_openai_chat_chunk',
    'encode_openai_done_event',
    'encode_sse_event',
    'iter_openai_chat_sse',
    'stream_openai_chat_sse',
    'translate_session_event',
    'translate_session_event_to_openai_chunks',
    'translate_stream_event_to_openai_chunks',
]
