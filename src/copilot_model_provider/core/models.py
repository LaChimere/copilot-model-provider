"""Canonical internal data models for the provider service."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ExecutionMode = Literal['stateless', 'sessional']


class RuntimeHealth(BaseModel):
    """Health metadata for a runtime backend."""

    model_config = ConfigDict(frozen=True)

    runtime: str = Field(min_length=1)
    available: bool
    detail: str | None = None


class InternalHealthResponse(BaseModel):
    """Response shape for the internal-only health endpoint."""

    model_config = ConfigDict(frozen=True)

    status: Literal['ok'] = 'ok'
    service: str = Field(min_length=1)
    environment: str = Field(min_length=1)
    runtime: RuntimeHealth


class CanonicalRequest(BaseModel):
    """Minimal normalized request contract for later provider phases."""

    model_config = ConfigDict(frozen=True)

    request_id: str | None = None
    conversation_id: str | None = None
    model_alias: str | None = None
    execution_mode: ExecutionMode = 'stateless'


class CanonicalChatMessage(BaseModel):
    """Normalized chat message used by the provider's internal execution path."""

    model_config = ConfigDict(frozen=True)

    role: Literal['system', 'user', 'assistant']
    content: str = Field(min_length=1)


class CanonicalChatRequest(BaseModel):
    """Canonical non-streaming chat request passed to runtime adapters."""

    model_config = ConfigDict(frozen=True)

    request_id: str | None = None
    conversation_id: str | None = None
    model_alias: str = Field(min_length=1)
    execution_mode: ExecutionMode = 'stateless'
    messages: list[CanonicalChatMessage] = Field(min_length=1)
    stream: bool = False


class ModelCatalogEntry(BaseModel):
    """Service-owned catalog entry used for public model listing and routing."""

    model_config = ConfigDict(frozen=True)

    alias: str = Field(min_length=1)
    runtime: str = Field(min_length=1)
    owned_by: str = Field(min_length=1)
    runtime_model_id: str = Field(min_length=1)
    created: int = Field(ge=0, default=0)
    session_mode: ExecutionMode = 'stateless'


class OpenAIModelCard(BaseModel):
    """OpenAI-compatible model card returned from ``GET /v1/models``."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    object: Literal['model'] = 'model'
    created: int = Field(ge=0, default=0)
    owned_by: str = Field(min_length=1)


class OpenAIModelListResponse(BaseModel):
    """OpenAI-compatible response body for the model catalog endpoint."""

    model_config = ConfigDict(frozen=True)

    object: Literal['list'] = 'list'
    data: list[OpenAIModelCard]


class OpenAIChatMessage(BaseModel):
    """OpenAI-compatible chat message representation."""

    model_config = ConfigDict(frozen=True)

    role: Literal['system', 'user', 'assistant']
    content: str = Field(min_length=1)


class OpenAIChatCompletionRequest(BaseModel):
    """OpenAI-compatible request body for non-streaming chat completions."""

    model_config = ConfigDict(frozen=True)

    model: str = Field(min_length=1)
    messages: list[OpenAIChatMessage] = Field(min_length=1)
    stream: bool = False


class OpenAIChatCompletionChoice(BaseModel):
    """Single non-streaming choice in an OpenAI-compatible chat response."""

    model_config = ConfigDict(frozen=True)

    index: int = Field(ge=0)
    message: OpenAIChatMessage
    finish_reason: Literal['stop', 'length', 'content_filter', 'tool_calls']


class OpenAIUsage(BaseModel):
    """Token accounting returned by OpenAI-compatible chat responses."""

    model_config = ConfigDict(frozen=True)

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class OpenAIChatCompletionResponse(BaseModel):
    """OpenAI-compatible response body for non-streaming chat completions."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    object: Literal['chat.completion'] = 'chat.completion'
    created: int = Field(ge=0)
    model: str = Field(min_length=1)
    choices: list[OpenAIChatCompletionChoice] = Field(min_length=1)
    usage: OpenAIUsage | None = None


class ResolvedRoute(BaseModel):
    """Minimal route resolution contract for runtime selection."""

    model_config = ConfigDict(frozen=True)

    runtime: str = Field(min_length=1)
    session_mode: ExecutionMode = 'stateless'
    runtime_model_id: str | None = None


class RuntimeCompletion(BaseModel):
    """Normalized runtime completion returned from a backend adapter."""

    model_config = ConfigDict(frozen=True)

    output_text: str = Field(min_length=1)
    finish_reason: Literal['stop', 'length', 'content_filter', 'tool_calls'] = 'stop'
    provider_response_id: str | None = None
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
