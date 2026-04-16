"""Canonical internal data models for the provider service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from collections.abc import Sequence

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


class CanonicalToolDefinition(BaseModel):
    """Normalized tool definition forwarded into a Copilot SDK session."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    description: str = ''
    parameters: dict[str, Any] | None = None


class CanonicalToolCall(BaseModel):
    """Normalized external tool request emitted by the runtime."""

    model_config = ConfigDict(frozen=True)

    call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: Any = None


class CanonicalToolResult(BaseModel):
    """Normalized client-supplied tool result returned on a later turn."""

    model_config = ConfigDict(frozen=True)

    call_id: str = Field(min_length=1)
    output_text: str = ''
    is_error: bool = False
    error_text: str | None = None


CanonicalToolRoutingSurface = Literal['openai_responses', 'anthropic_messages']
CanonicalToolRoutingMode = Literal['none', 'client_passthrough']

_CLIENT_PASSTHROUGH_EXCLUDED_BUILTIN_TOOLS = ('web_search', 'web_fetch')
_CLIENT_PASSTHROUGH_GUIDANCE = (
    'When tools are available, prefer the provided external or MCP tools for '
    'actions and for current-information research. Use them directly in this '
    'turn when needed, instead of ending your turn with a plan to use them later.'
)


class CanonicalToolRoutingHint(BaseModel):
    """Preserved northbound tool-routing hints carried into runtime policy.

    Attributes:
        surface: Public request surface that supplied the routing hint.
        tool_choice: Optional OpenAI Responses tool-choice payload preserved as a
            routing hint. The provider does not yet guarantee full enforcement of
            this hint, but preserves it so the shared policy can make
            evidence-backed routing decisions.
        parallel_tool_calls: Optional OpenAI Responses parallel-tool-calls hint
            preserved alongside ``tool_choice`` for the same reason.

    """

    model_config = ConfigDict(frozen=True)

    surface: CanonicalToolRoutingSurface
    tool_choice: str | dict[str, Any] | None = None
    parallel_tool_calls: bool | None = None


def _empty_excluded_builtin_tool_tuple() -> tuple[str, ...]:
    """Return a typed empty tuple for excluded built-in tool collections."""
    return ()


class CanonicalToolRoutingPolicy(BaseModel):
    """Canonical policy describing how one request should route tool-aware turns.

    Attributes:
        mode: Whether the runtime should treat the request as a regular stateless
            chat turn or as a client-passthrough tool-aware session.
        hint: Optional preserved northbound routing hint payload.
        excluded_builtin_tools: SDK built-in tools that should yield to
            northbound client tools for this request.
        guidance: Optional guidance message prepended to tool-aware prompts so
            the model prefers the client-visible external tool loop.

    """

    model_config = ConfigDict(frozen=True)

    mode: CanonicalToolRoutingMode = 'none'
    hint: CanonicalToolRoutingHint | None = None
    excluded_builtin_tools: tuple[str, ...] = Field(
        default_factory=_empty_excluded_builtin_tool_tuple
    )
    guidance: str | None = None


def _empty_canonical_tool_definition_list() -> list[CanonicalToolDefinition]:
    """Return a typed empty list for canonical tool-definition collections."""
    return []


def _empty_canonical_tool_result_list() -> list[CanonicalToolResult]:
    """Return a typed empty list for canonical tool-result collections."""
    return []


def _empty_canonical_chat_message_list() -> list[CanonicalChatMessage]:
    """Return a typed empty list for canonical chat-message collections."""
    return []


def _default_tool_routing_policy() -> CanonicalToolRoutingPolicy:
    """Return the no-op routing policy used for non-tool requests."""
    return CanonicalToolRoutingPolicy()


def _has_tool_routing_context(
    *,
    session_id: str | None,
    tool_definitions: Sequence[CanonicalToolDefinition],
    tool_results: Sequence[CanonicalToolResult],
) -> bool:
    """Report whether a normalized request needs tool-aware runtime routing."""
    return bool(session_id or tool_definitions or tool_results)


def _build_tool_routing_hint(
    *,
    surface: CanonicalToolRoutingSurface | None,
    tool_choice: str | dict[str, Any] | None,
    parallel_tool_calls: bool | None,
) -> CanonicalToolRoutingHint | None:
    """Build the preserved northbound routing hint when one applies."""
    if surface != 'openai_responses':
        return None

    return CanonicalToolRoutingHint(
        surface=surface,
        tool_choice=tool_choice,
        parallel_tool_calls=parallel_tool_calls,
    )


def derive_tool_routing_policy(
    *,
    surface: CanonicalToolRoutingSurface | None = None,
    session_id: str | None = None,
    tool_definitions: Sequence[CanonicalToolDefinition] = (),
    tool_results: Sequence[CanonicalToolResult] = (),
    tool_choice: str | dict[str, Any] | None = None,
    parallel_tool_calls: bool | None = None,
) -> CanonicalToolRoutingPolicy:
    """Derive the canonical routing policy for one normalized request.

    Args:
        surface: Optional public protocol surface that supplied the request.
        session_id: Provider-side continuation session identifier, when this
            request resumes a prior tool-aware turn.
        tool_definitions: Normalized client-visible tool definitions present on
            the request.
        tool_results: Normalized tool results supplied by a continuation turn.
        tool_choice: Optional OpenAI Responses tool-choice payload preserved as
            a routing hint.
        parallel_tool_calls: Optional OpenAI Responses parallel-tool-calls hint
            preserved as part of the same routing context.

    Returns:
        A no-op policy for regular stateless chat requests, or a
        ``client_passthrough`` policy for tool-aware requests.

    """
    if not _has_tool_routing_context(
        session_id=session_id,
        tool_definitions=tool_definitions,
        tool_results=tool_results,
    ):
        return _default_tool_routing_policy()

    return CanonicalToolRoutingPolicy(
        mode='client_passthrough',
        hint=_build_tool_routing_hint(
            surface=surface,
            tool_choice=tool_choice,
            parallel_tool_calls=parallel_tool_calls,
        ),
        excluded_builtin_tools=_CLIENT_PASSTHROUGH_EXCLUDED_BUILTIN_TOOLS,
        guidance=_CLIENT_PASSTHROUGH_GUIDANCE,
    )


class CanonicalChatRequest(BaseModel):
    """Canonical chat request passed to runtime implementations."""

    model_config = ConfigDict(frozen=True)

    request_id: str | None = None
    conversation_id: str | None = None
    session_id: str | None = None
    runtime_auth_token: str | None = None
    model_id: str = Field(min_length=1)
    messages: list[CanonicalChatMessage] = Field(
        default_factory=_empty_canonical_chat_message_list
    )
    tool_definitions: list[CanonicalToolDefinition] = Field(
        default_factory=_empty_canonical_tool_definition_list
    )
    tool_results: list[CanonicalToolResult] = Field(
        default_factory=_empty_canonical_tool_result_list
    )
    tool_routing_policy: CanonicalToolRoutingPolicy = Field(
        default_factory=_default_tool_routing_policy
    )
    stream: bool = False


class CopilotModelVisionLimits(BaseModel):
    """Vision-specific limits exposed through provider-owned model metadata."""

    model_config = ConfigDict(frozen=True)

    supported_media_types: list[str] | None = None
    max_prompt_images: int | None = Field(default=None, ge=0)
    max_prompt_image_size: int | None = Field(default=None, ge=0)


class CopilotModelLimits(BaseModel):
    """Token and media limits exposed through provider-owned model metadata."""

    model_config = ConfigDict(frozen=True)

    max_prompt_tokens: int | None = Field(default=None, ge=0)
    max_context_window_tokens: int | None = Field(default=None, ge=0)
    vision: CopilotModelVisionLimits | None = None


class CopilotModelSupports(BaseModel):
    """Capability flags exposed through provider-owned model metadata."""

    model_config = ConfigDict(frozen=True)

    vision: bool | None = None
    reasoning_effort: bool | None = None


class CopilotModelCapabilities(BaseModel):
    """Normalized capability metadata preserved from runtime model discovery."""

    model_config = ConfigDict(frozen=True)

    supports: CopilotModelSupports | None = None
    limits: CopilotModelLimits | None = None


class CopilotModelPolicy(BaseModel):
    """Runtime policy metadata exposed through provider-owned model metadata."""

    model_config = ConfigDict(frozen=True)

    state: str = Field(min_length=1)
    terms: str = Field(min_length=1)


class CopilotModelBilling(BaseModel):
    """Runtime billing metadata exposed through provider-owned model metadata."""

    model_config = ConfigDict(frozen=True)

    multiplier: float


class CopilotModelMetadata(BaseModel):
    """Provider-owned nested model metadata shape shared across protocol facades."""

    model_config = ConfigDict(frozen=True)

    name: str | None = Field(default=None, min_length=1)
    capabilities: CopilotModelCapabilities | None = None
    policy: CopilotModelPolicy | None = None
    billing: CopilotModelBilling | None = None
    supported_reasoning_efforts: list[str] | None = None
    default_reasoning_effort: str | None = Field(default=None, min_length=1)


class RuntimeDiscoveredModel(BaseModel):
    """Normalized live runtime model discovered for one auth-context snapshot.

    Attributes:
        id: Stable runtime model identifier visible to the current auth context.
        created: Optional created timestamp exposed through compatibility facades.
            The Copilot runtime currently does not supply this, so the default
            remains ``0`` until a runtime provides a richer value.
        copilot: Optional provider-owned metadata preserved from runtime model
            discovery and later exposed through compatibility model-list routes.

    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    created: int = Field(ge=0, default=0)
    copilot: CopilotModelMetadata | None = None


class ModelCatalogEntry(BaseModel):
    """Service-owned catalog entry used for public model listing and routing."""

    model_config = ConfigDict(frozen=True)

    alias: str = Field(min_length=1)
    runtime: str = Field(min_length=1)
    owned_by: str = Field(min_length=1)
    runtime_model_id: str = Field(min_length=1)
    created: int = Field(ge=0, default=0)
    copilot: CopilotModelMetadata | None = None


class OpenAIModelCard(BaseModel):
    """OpenAI-compatible model card returned from ``GET /v1/models``."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    object: Literal['model'] = 'model'
    created: int = Field(ge=0, default=0)
    owned_by: str = Field(min_length=1)
    copilot: CopilotModelMetadata | None = None


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
    max_input_tokens: int | None = Field(default=None, ge=0)
    copilot: CopilotModelMetadata | None = None


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


def _empty_anthropic_content_block_list() -> list[
    AnthropicTextContentBlock | AnthropicToolUseContentBlock
]:
    """Return a typed empty list for Anthropic content-block collections."""
    return []


class OpenAIResponsesInputContentPart(BaseModel):
    """One Responses input content part accepted by the minimal route.

    The provider only normalizes text-bearing content onto the internal
    canonical chat path, but desktop and CLI clients may still include other
    structured content parts such as image/file references. Accepting those
    parts here prevents FastAPI request validation from rejecting otherwise
    usable prompts before the normalization layer can safely ignore the
    non-text-bearing items.

    """

    model_config = ConfigDict(frozen=True)

    type: str = Field(min_length=1)
    text: str | None = None


class OpenAIResponsesInputMessage(BaseModel):
    """Structured message item accepted by the minimal Responses route."""

    model_config = ConfigDict(frozen=True)

    type: Literal['message'] = 'message'
    role: Literal['system', 'developer', 'user', 'assistant']
    content: str | list[OpenAIResponsesInputContentPart] = Field(min_length=1)


class OpenAIResponsesFunctionCallOutputItem(BaseModel):
    """Tool-result item accepted by continuation turns on the Responses route."""

    model_config = ConfigDict(frozen=True)

    type: Literal['function_call_output'] = 'function_call_output'
    call_id: str = Field(min_length=1)
    output: Any = None


class OpenAIResponsesFunctionCallReplayItem(BaseModel):
    """Replayed function-call item accepted on continuation turns.

    Some OpenAI-compatible clients replay the prior assistant tool call inside
    ``input`` alongside the matching ``function_call_output`` item instead of
    using ``previous_response_id``. The provider accepts and ignores this item
    because the interactive runtime only needs the call id plus tool result.

    """

    model_config = ConfigDict(frozen=True)

    type: Literal['function_call'] = 'function_call'
    call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: Any = None


class OpenAIResponsesCreateRequest(BaseModel):
    """OpenAI-compatible request body for the minimal Responses route.

    This request model intentionally stays thin: it accepts the Codex-needed
    subset and ignores unrelated optional fields rather than inventing a new
    provider-specific wrapper on top of the Responses wire format.

    """

    model_config = ConfigDict(frozen=True)

    model: str = Field(min_length=1)
    input: (
        str
        | list[
            OpenAIResponsesInputMessage
            | OpenAIResponsesFunctionCallReplayItem
            | OpenAIResponsesFunctionCallOutputItem
        ]
    ) = Field(min_length=1)
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


class OpenAIResponsesFunctionCall(BaseModel):
    """Function-call output item returned by the Responses route."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    type: Literal['function_call'] = 'function_call'
    status: Literal['in_progress', 'completed'] = 'completed'
    call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: str = ''


OpenAIResponsesOutputItem = OpenAIResponsesOutputMessage | OpenAIResponsesFunctionCall


def _empty_responses_output_item_list() -> list[OpenAIResponsesOutputItem]:
    """Return a typed empty list for Responses output-item collections."""
    return []


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
    output: list[OpenAIResponsesOutputItem] = Field(
        default_factory=_empty_responses_output_item_list
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
    item: OpenAIResponsesOutputItem


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
    item: OpenAIResponsesOutputItem


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


class AnthropicToolUseContentBlock(BaseModel):
    """Anthropic-compatible tool-use block returned by the Messages facade."""

    model_config = ConfigDict(frozen=True)

    type: Literal['tool_use'] = 'tool_use'
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    input: dict[str, Any] = Field(default_factory=dict)


class AnthropicMessageInput(BaseModel):
    """One Anthropic Messages API input message."""

    model_config = ConfigDict(frozen=True)

    role: Literal['user', 'assistant']
    content: str | list[dict[str, Any]] = Field(min_length=1)


class AnthropicMessagesCreateRequest(BaseModel):
    """Minimal Anthropic Messages request accepted by the provider facade.

    The provider intentionally accepts the fields Claude Code sends in gateway
    mode, but only normalizes the text-bearing subset onto the internal
    ``CanonicalChatRequest`` path. Tool definitions are preserved so tool-aware
    Anthropic requests can participate in the shared client-passthrough routing
    policy, while tool execution itself remains outside the provider boundary.

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
    content: list[AnthropicTextContentBlock | AnthropicToolUseContentBlock] = Field(
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
    content_block: AnthropicTextContentBlock | AnthropicToolUseContentBlock


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

    output_text: str | None = None
    finish_reason: Literal['stop', 'length', 'content_filter', 'tool_calls'] = 'stop'
    provider_response_id: str | None = None
    session_id: str | None = None
    pending_tool_calls: tuple[CanonicalToolCall, ...] = Field(default_factory=tuple)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
