"""Canonical internal data models for the provider service."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

AnthropicStopReason = Literal['end_turn', 'max_tokens', 'stop_sequence', 'tool_use']


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


class CanonicalChatMessage(BaseModel):
    """Normalized chat message used by the provider's internal execution path."""

    model_config = ConfigDict(frozen=True)

    role: Literal['system', 'user', 'assistant']
    content: str = Field(min_length=1)


class CanonicalChatRequest(BaseModel):
    """Canonical chat request passed to runtime implementations."""

    model_config = ConfigDict(frozen=True)

    request_id: str | None = None
    conversation_id: str | None = None
    runtime_auth_token: str | None = None
    model_id: str = Field(min_length=1)
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


class AnthropicModelInfo(BaseModel):
    """Minimal Anthropic-compatible model info returned from ``GET /v1/models``."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    type: Literal['model'] = 'model'
    display_name: str = Field(min_length=1)
    created_at: str = Field(min_length=1)


class AnthropicModelListResponse(BaseModel):
    """Anthropic-compatible response body for the models catalog endpoint."""

    model_config = ConfigDict(frozen=True)

    data: list[AnthropicModelInfo]
    first_id: str | None = None
    has_more: bool = False
    last_id: str | None = None


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


def _empty_json_object_list() -> list[dict[str, Any]]:
    """Return a typed empty list for JSON-like object payload collections."""
    return []


def _empty_responses_output_text_list() -> list[OpenAIResponsesOutputText]:
    """Return a typed empty list for Responses output-text collections."""
    return []


def _empty_responses_output_message_list() -> list[OpenAIResponsesOutputMessage]:
    """Return a typed empty list for Responses output-message collections."""
    return []


def _empty_anthropic_content_block_list() -> list[AnthropicTextContentBlock]:
    """Return a typed empty list for Anthropic content-block collections."""
    return []


class OpenAIResponsesInputTextPart(BaseModel):
    """Text-bearing content part accepted by the minimal Responses route."""

    model_config = ConfigDict(frozen=True)

    type: Literal['input_text', 'output_text', 'text']
    text: str = Field(min_length=1)


class OpenAIResponsesInputMessage(BaseModel):
    """Structured message item accepted by the minimal Responses route."""

    model_config = ConfigDict(frozen=True)

    type: Literal['message'] = 'message'
    role: Literal['system', 'developer', 'user', 'assistant']
    content: str | list[OpenAIResponsesInputTextPart] = Field(min_length=1)


class OpenAIResponsesCreateRequest(BaseModel):
    """OpenAI-compatible request body for the minimal Responses route.

    This request model intentionally stays thin: it accepts the Codex-needed
    subset and ignores unrelated optional fields rather than inventing a new
    provider-specific wrapper on top of the Responses wire format.

    """

    model_config = ConfigDict(frozen=True)

    model: str = Field(min_length=1)
    input: str | list[OpenAIResponsesInputMessage] = Field(min_length=1)
    instructions: str | list[OpenAIResponsesInputMessage] | None = None
    stream: bool = False
    store: bool = False
    truncation: Literal['auto', 'disabled'] | None = None
    previous_response_id: str | None = None
    parallel_tool_calls: bool = False
    tool_choice: str | dict[str, Any] | None = None
    tools: list[dict[str, Any]] = Field(default_factory=_empty_json_object_list)
    include: list[str] = Field(default_factory=list)
    prompt_cache_key: str | None = None
    reasoning: dict[str, object] | None = None


class OpenAIResponsesOutputText(BaseModel):
    """Assistant text content returned by the minimal Responses route."""

    model_config = ConfigDict(frozen=True)

    type: Literal['output_text'] = 'output_text'
    text: str
    annotations: list[dict[str, Any]] = Field(default_factory=_empty_json_object_list)


class OpenAIResponsesOutputMessage(BaseModel):
    """Assistant output item returned inside a completed Responses payload."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    type: Literal['message'] = 'message'
    status: Literal['in_progress', 'completed'] = 'completed'
    role: Literal['assistant'] = 'assistant'
    content: list[OpenAIResponsesOutputText] = Field(
        default_factory=_empty_responses_output_text_list
    )
    phase: Literal['commentary', 'final_answer'] | None = 'final_answer'


class OpenAIResponsesUsage(BaseModel):
    """Token accounting returned by the minimal Responses route."""

    model_config = ConfigDict(frozen=True)

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class OpenAIResponsesConversation(BaseModel):
    """Conversation metadata exposed by the minimal Responses route."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)


class OpenAIResponse(BaseModel):
    """OpenAI-compatible response body for the minimal Responses route."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    object: Literal['response'] = 'response'
    created_at: int = Field(ge=0)
    status: Literal['completed', 'in_progress']
    model: str = Field(min_length=1)
    output: list[OpenAIResponsesOutputMessage] = Field(
        default_factory=_empty_responses_output_message_list
    )
    parallel_tool_calls: bool = False
    tool_choice: str | dict[str, Any] | None = None
    tools: list[dict[str, Any]] = Field(default_factory=_empty_json_object_list)
    store: bool = False
    instructions: str | list[OpenAIResponsesInputMessage] | None = None
    usage: OpenAIResponsesUsage | None = None
    previous_response_id: str | None = None
    conversation: OpenAIResponsesConversation | None = None
    completed_at: int | None = Field(default=None, ge=0)


class OpenAIResponsesCreatedEvent(BaseModel):
    """Streaming event emitted when a Responses stream has been created."""

    model_config = ConfigDict(frozen=True)

    type: Literal['response.created'] = 'response.created'
    sequence_number: int = Field(ge=0)
    response: OpenAIResponse


class OpenAIResponsesOutputItemAddedEvent(BaseModel):
    """Streaming event emitted when a response output item is added."""

    model_config = ConfigDict(frozen=True)

    type: Literal['response.output_item.added'] = 'response.output_item.added'
    sequence_number: int = Field(ge=0)
    output_index: int = Field(ge=0, default=0)
    item: OpenAIResponsesOutputMessage


class OpenAIResponsesContentPartAddedEvent(BaseModel):
    """Streaming event emitted when a content part is added to an output item."""

    model_config = ConfigDict(frozen=True)

    type: Literal['response.content_part.added'] = 'response.content_part.added'
    sequence_number: int = Field(ge=0)
    item_id: str = Field(min_length=1)
    output_index: int = Field(ge=0, default=0)
    content_index: int = Field(ge=0, default=0)
    part: OpenAIResponsesOutputText


class OpenAIResponsesOutputTextDeltaEvent(BaseModel):
    """Streaming event emitted for one assistant text delta."""

    model_config = ConfigDict(frozen=True)

    type: Literal['response.output_text.delta'] = 'response.output_text.delta'
    sequence_number: int = Field(ge=0)
    item_id: str = Field(min_length=1)
    output_index: int = Field(ge=0, default=0)
    content_index: int = Field(ge=0, default=0)
    delta: str = Field(min_length=1)
    logprobs: list[dict[str, Any]] = Field(default_factory=_empty_json_object_list)


class OpenAIResponsesOutputTextDoneEvent(BaseModel):
    """Streaming event emitted when an output-text part is finalized."""

    model_config = ConfigDict(frozen=True)

    type: Literal['response.output_text.done'] = 'response.output_text.done'
    sequence_number: int = Field(ge=0)
    item_id: str = Field(min_length=1)
    output_index: int = Field(ge=0, default=0)
    content_index: int = Field(ge=0, default=0)
    text: str
    logprobs: list[dict[str, Any]] = Field(default_factory=_empty_json_object_list)


class OpenAIResponsesContentPartDoneEvent(BaseModel):
    """Streaming event emitted when a content part is finalized."""

    model_config = ConfigDict(frozen=True)

    type: Literal['response.content_part.done'] = 'response.content_part.done'
    sequence_number: int = Field(ge=0)
    item_id: str = Field(min_length=1)
    output_index: int = Field(ge=0, default=0)
    content_index: int = Field(ge=0, default=0)
    part: OpenAIResponsesOutputText


class OpenAIResponsesOutputItemDoneEvent(BaseModel):
    """Streaming event emitted when an output item is finalized."""

    model_config = ConfigDict(frozen=True)

    type: Literal['response.output_item.done'] = 'response.output_item.done'
    sequence_number: int = Field(ge=0)
    output_index: int = Field(ge=0, default=0)
    item: OpenAIResponsesOutputMessage


class OpenAIResponsesCompletedEvent(BaseModel):
    """Streaming event emitted when a Responses stream has completed."""

    model_config = ConfigDict(frozen=True)

    type: Literal['response.completed'] = 'response.completed'
    sequence_number: int = Field(ge=0)
    response: OpenAIResponse


class AnthropicTextContentBlock(BaseModel):
    """Minimal text content block accepted and returned by the Anthropic facade."""

    model_config = ConfigDict(frozen=True)

    type: Literal['text'] = 'text'
    text: str = ''


class AnthropicMessageInput(BaseModel):
    """One Anthropic Messages API input message."""

    model_config = ConfigDict(frozen=True)

    role: Literal['user', 'assistant']
    content: str | list[dict[str, Any]] = Field(min_length=1)


class AnthropicMessagesCreateRequest(BaseModel):
    """Minimal Anthropic Messages request accepted by the provider facade.

    The provider intentionally accepts the fields Claude Code sends in gateway
    mode, but only normalizes the text-bearing subset onto the internal
    ``CanonicalChatRequest`` path. Tool definitions are accepted for compatibility
    and preserved in the request model, but the current provider does not execute
    Anthropic tool-use flows northbound.

    """

    model_config = ConfigDict(frozen=True)

    model: str = Field(min_length=1)
    messages: list[AnthropicMessageInput] = Field(min_length=1)
    system: str | list[dict[str, Any]] | None = None
    max_tokens: int | None = Field(default=None, ge=1)
    stream: bool = False
    metadata: dict[str, Any] | None = None
    tools: list[dict[str, Any]] = Field(default_factory=_empty_json_object_list)
    thinking: dict[str, Any] | None = None


class AnthropicMessagesCountTokensRequest(BaseModel):
    """Anthropic-compatible request body for ``POST /v1/messages/count_tokens``."""

    model_config = ConfigDict(frozen=True)

    model: str = Field(min_length=1)
    messages: list[AnthropicMessageInput] = Field(min_length=1)
    system: str | list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None
    tools: list[dict[str, Any]] = Field(default_factory=_empty_json_object_list)


class AnthropicUsage(BaseModel):
    """Token accounting returned by the Anthropic Messages facade."""

    model_config = ConfigDict(frozen=True)

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class AnthropicCountTokensResponse(BaseModel):
    """Anthropic-compatible response body for ``POST /v1/messages/count_tokens``."""

    model_config = ConfigDict(frozen=True)

    input_tokens: int = Field(ge=0)


class AnthropicMessageResponse(BaseModel):
    """Minimal Anthropic-compatible response body for ``POST /v1/messages``."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    type: Literal['message'] = 'message'
    role: Literal['assistant'] = 'assistant'
    model: str = Field(min_length=1)
    content: list[AnthropicTextContentBlock] = Field(
        default_factory=_empty_anthropic_content_block_list
    )
    stop_reason: AnthropicStopReason | None = 'end_turn'
    stop_sequence: str | None = None
    usage: AnthropicUsage | None = None


class AnthropicMessageStartEvent(BaseModel):
    """Streaming event emitted when an Anthropic message stream starts."""

    model_config = ConfigDict(frozen=True)

    type: Literal['message_start'] = 'message_start'
    message: AnthropicMessageResponse


class AnthropicContentBlockStartEvent(BaseModel):
    """Streaming event emitted when an Anthropic content block starts."""

    model_config = ConfigDict(frozen=True)

    type: Literal['content_block_start'] = 'content_block_start'
    index: int = Field(ge=0, default=0)
    content_block: AnthropicTextContentBlock


class AnthropicTextDelta(BaseModel):
    """Text delta payload emitted inside Anthropic content-block events."""

    model_config = ConfigDict(frozen=True)

    type: Literal['text_delta'] = 'text_delta'
    text: str = Field(min_length=1)


class AnthropicContentBlockDeltaEvent(BaseModel):
    """Streaming event emitted for one Anthropic text delta."""

    model_config = ConfigDict(frozen=True)

    type: Literal['content_block_delta'] = 'content_block_delta'
    index: int = Field(ge=0, default=0)
    delta: AnthropicTextDelta


class AnthropicContentBlockStopEvent(BaseModel):
    """Streaming event emitted when an Anthropic content block completes."""

    model_config = ConfigDict(frozen=True)

    type: Literal['content_block_stop'] = 'content_block_stop'
    index: int = Field(ge=0, default=0)


class AnthropicMessageDelta(BaseModel):
    """Top-level Anthropic message delta emitted near stream completion."""

    model_config = ConfigDict(frozen=True)

    stop_reason: AnthropicStopReason | None = 'end_turn'
    stop_sequence: str | None = None


class AnthropicMessageDeltaEvent(BaseModel):
    """Streaming event emitted for top-level Anthropic message updates."""

    model_config = ConfigDict(frozen=True)

    type: Literal['message_delta'] = 'message_delta'
    delta: AnthropicMessageDelta
    usage: AnthropicUsage | None = None


class AnthropicMessageStopEvent(BaseModel):
    """Streaming event emitted when an Anthropic message stream completes."""

    model_config = ConfigDict(frozen=True)

    type: Literal['message_stop'] = 'message_stop'


class ResolvedRoute(BaseModel):
    """Minimal route resolution contract for runtime selection."""

    model_config = ConfigDict(frozen=True)

    runtime: str = Field(min_length=1)
    runtime_model_id: str | None = None


class RuntimeCompletion(BaseModel):
    """Normalized runtime completion returned from a backend runtime."""

    model_config = ConfigDict(frozen=True)

    output_text: str = Field(min_length=1)
    finish_reason: Literal['stop', 'length', 'content_filter', 'tool_calls'] = 'stop'
    provider_response_id: str | None = None
    session_id: str | None = None
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
