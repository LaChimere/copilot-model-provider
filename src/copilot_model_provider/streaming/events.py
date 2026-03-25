"""Streaming transport models used by the OpenAI-compatible chat surface."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

StreamFinishReason = Literal['stop', 'length', 'content_filter', 'tool_calls']


class OpenAIChatCompletionChunkDelta(BaseModel):
    """Delta payload emitted inside an OpenAI-compatible streaming chunk."""

    model_config = ConfigDict(frozen=True)

    role: Literal['assistant'] | None = None
    content: str | None = None


class OpenAIChatCompletionChunkChoice(BaseModel):
    """Single choice payload emitted by a streaming chat completion."""

    model_config = ConfigDict(frozen=True)

    index: int = Field(ge=0)
    delta: OpenAIChatCompletionChunkDelta
    finish_reason: StreamFinishReason | None = None


class OpenAIChatCompletionChunk(BaseModel):
    """OpenAI-compatible chunk encoded into SSE frames for chat streaming."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    object: Literal['chat.completion.chunk'] = 'chat.completion.chunk'
    created: int = Field(ge=0)
    model: str = Field(min_length=1)
    choices: list[OpenAIChatCompletionChunkChoice] = Field(min_length=1)


class AssistantTextDeltaEvent(BaseModel):
    """Canonical assistant text delta emitted by the streaming adapter layer."""

    model_config = ConfigDict(frozen=True)

    kind: Literal['assistant_text_delta'] = 'assistant_text_delta'
    text: str = Field(min_length=1)


class AssistantTurnCompleteEvent(BaseModel):
    """Canonical terminal event emitted when an assistant turn finishes."""

    model_config = ConfigDict(frozen=True)

    kind: Literal['assistant_turn_complete'] = 'assistant_turn_complete'
    finish_reason: StreamFinishReason = 'stop'


class StreamingErrorEvent(BaseModel):
    """Canonical event emitted when the runtime reports a stream-level error."""

    model_config = ConfigDict(frozen=True)

    kind: Literal['streaming_error'] = 'streaming_error'
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


CanonicalStreamingEvent = (
    AssistantTextDeltaEvent | AssistantTurnCompleteEvent | StreamingErrorEvent
)
