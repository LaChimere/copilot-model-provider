"""Normalization and translation helpers for the OpenAI Responses surface."""

from __future__ import annotations

import json
from time import time
from typing import Any, Literal, cast
from uuid import uuid4

from copilot_model_provider.core.models import (
    CanonicalChatMessage,
    CanonicalChatRequest,
    CanonicalToolCall,
    CanonicalToolDefinition,
    CanonicalToolResult,
    OpenAIResponse,
    OpenAIResponsesCompletedEvent,
    OpenAIResponsesContentPartAddedEvent,
    OpenAIResponsesContentPartDoneEvent,
    OpenAIResponsesConversation,
    OpenAIResponsesCreatedEvent,
    OpenAIResponsesCreateRequest,
    OpenAIResponsesFunctionCall,
    OpenAIResponsesFunctionCallOutputItem,
    OpenAIResponsesFunctionCallReplayItem,
    OpenAIResponsesInputContentPart,
    OpenAIResponsesInputMessage,
    OpenAIResponsesOutputItem,
    OpenAIResponsesOutputItemAddedEvent,
    OpenAIResponsesOutputItemDoneEvent,
    OpenAIResponsesOutputMessage,
    OpenAIResponsesOutputText,
    OpenAIResponsesOutputTextDeltaEvent,
    OpenAIResponsesOutputTextDoneEvent,
    OpenAIResponsesUsage,
    RuntimeCompletion,
    derive_tool_routing_policy,
)


def normalize_openai_responses_request(
    *,
    request: OpenAIResponsesCreateRequest,
    request_id: str | None = None,
    conversation_id: str | None = None,
    session_id: str | None = None,
    runtime_auth_token: str | None = None,
) -> CanonicalChatRequest:
    """Normalize an OpenAI Responses request into the provider chat contract."""
    tool_definitions = _normalize_openai_tool_definitions(tools=request.tools)
    messages, tool_results = _normalize_openai_responses_input(
        instructions=request.instructions,
        input_value=request.input,
    )

    return CanonicalChatRequest(
        request_id=request_id,
        conversation_id=conversation_id,
        session_id=session_id,
        runtime_auth_token=runtime_auth_token,
        model_id=request.model,
        messages=messages,
        tool_definitions=tool_definitions,
        tool_results=tool_results,
        tool_routing_policy=derive_tool_routing_policy(
            surface='openai_responses',
            session_id=session_id,
            tool_definitions=tool_definitions,
            tool_results=tool_results,
            tool_choice=request.tool_choice,
            parallel_tool_calls=request.parallel_tool_calls,
        ),
        stream=request.stream,
    )


def build_response_id(*, request_id: str | None = None) -> str:
    """Build a stable Responses-style identifier for one provider request."""
    resolved_request_id = request_id or uuid4().hex
    return (
        resolved_request_id
        if resolved_request_id.startswith('resp_')
        else f'resp_{resolved_request_id}'
    )


def build_response_message_id(*, response_id: str) -> str:
    """Build the assistant-message identifier for one Responses payload."""
    suffix = response_id.removeprefix('resp_')
    return f'msg_{suffix}'


def build_openai_responses_response_from_completion(
    *,
    request: OpenAIResponsesCreateRequest,
    completion: RuntimeCompletion,
    response_id: str,
    conversation_id: str | None = None,
    created_at: int | None = None,
) -> OpenAIResponse:
    """Translate a runtime completion into the public Responses payload."""
    return build_openai_responses_response_from_text(
        request=request,
        output_text=completion.output_text,
        pending_tool_call=completion.pending_tool_call,
        response_id=response_id,
        conversation_id=conversation_id,
        created_at=created_at,
        usage=build_openai_responses_usage(
            prompt_tokens=completion.prompt_tokens,
            completion_tokens=completion.completion_tokens,
        ),
    )


def build_openai_responses_response_from_text(
    *,
    request: OpenAIResponsesCreateRequest,
    output_text: str | None,
    pending_tool_call: CanonicalToolCall | None = None,
    response_id: str,
    conversation_id: str | None = None,
    created_at: int | None = None,
    completed_at: int | None = None,
    status: Literal['completed', 'in_progress'] = 'completed',
    usage: OpenAIResponsesUsage | None = None,
) -> OpenAIResponse:
    """Build a Responses payload from assistant text and optional tool call."""
    normalized_created_at = created_at or int(time())
    normalized_completed_at = completed_at or (
        normalized_created_at if status == 'completed' else None
    )
    output: list[OpenAIResponsesOutputItem] = []
    if output_text is not None:
        output.append(
            build_openai_responses_output_message(
                response_id=response_id,
                output_text=output_text,
                status=status,
            )
        )
    if pending_tool_call is not None:
        output.append(
            build_openai_responses_function_call_item(
                response_id=response_id,
                tool_call=pending_tool_call,
            )
        )

    return OpenAIResponse(
        id=response_id,
        created_at=normalized_created_at,
        completed_at=normalized_completed_at,
        status=status,
        model=request.model,
        instructions=request.instructions,
        output=output,
        parallel_tool_calls=request.parallel_tool_calls,
        tool_choice=request.tool_choice,
        tools=_normalize_openai_response_tools(tools=request.tools),
        store=request.store,
        usage=usage,
        previous_response_id=request.previous_response_id,
        conversation=(
            OpenAIResponsesConversation(id=conversation_id)
            if conversation_id is not None
            else None
        ),
    )


def build_openai_responses_created_event(
    *,
    request: OpenAIResponsesCreateRequest,
    response_id: str,
    sequence_number: int,
    conversation_id: str | None = None,
    created_at: int | None = None,
) -> OpenAIResponsesCreatedEvent:
    """Build the initial streaming lifecycle event for one response stream."""
    return OpenAIResponsesCreatedEvent(
        sequence_number=sequence_number,
        response=build_openai_responses_response_from_text(
            request=request,
            output_text=None,
            pending_tool_call=None,
            response_id=response_id,
            conversation_id=conversation_id,
            created_at=created_at,
            status='in_progress',
        ),
    )


def build_openai_responses_completed_event(
    *,
    request: OpenAIResponsesCreateRequest,
    response_id: str,
    output_text: str | None,
    pending_tool_call: CanonicalToolCall | None,
    sequence_number: int,
    conversation_id: str | None = None,
    created_at: int | None = None,
    completed_at: int | None = None,
    usage: OpenAIResponsesUsage | None = None,
) -> OpenAIResponsesCompletedEvent:
    """Build the terminal lifecycle event for one streamed response."""
    return OpenAIResponsesCompletedEvent(
        sequence_number=sequence_number,
        response=build_openai_responses_response_from_text(
            request=request,
            output_text=output_text,
            pending_tool_call=pending_tool_call,
            response_id=response_id,
            conversation_id=conversation_id,
            created_at=created_at,
            completed_at=completed_at,
            status='completed',
            usage=usage,
        ),
    )


def build_openai_responses_usage(
    *,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> OpenAIResponsesUsage | None:
    """Build a Responses usage payload when token accounting is available."""
    if prompt_tokens is None or completion_tokens is None:
        return None

    return OpenAIResponsesUsage(
        input_tokens=prompt_tokens,
        output_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )


def build_openai_responses_output_text_delta_event(
    *,
    response_id: str,
    text: str,
    sequence_number: int,
    output_index: int = 0,
    content_index: int = 0,
) -> OpenAIResponsesOutputTextDeltaEvent:
    """Build one ``response.output_text.delta`` event for a streamed response."""
    return OpenAIResponsesOutputTextDeltaEvent(
        sequence_number=sequence_number,
        item_id=build_response_message_id(response_id=response_id),
        output_index=output_index,
        content_index=content_index,
        delta=text,
    )


def build_openai_responses_output_text_done_event(
    *,
    response_id: str,
    text: str,
    sequence_number: int,
    output_index: int = 0,
    content_index: int = 0,
) -> OpenAIResponsesOutputTextDoneEvent:
    """Build one ``response.output_text.done`` event for a streamed response."""
    return OpenAIResponsesOutputTextDoneEvent(
        sequence_number=sequence_number,
        item_id=build_response_message_id(response_id=response_id),
        output_index=output_index,
        content_index=content_index,
        text=text,
    )


def build_openai_responses_content_part_added_event(
    *,
    response_id: str,
    sequence_number: int,
    output_index: int = 0,
    content_index: int = 0,
) -> OpenAIResponsesContentPartAddedEvent:
    """Build one ``response.content_part.added`` event for a response stream."""
    return OpenAIResponsesContentPartAddedEvent(
        sequence_number=sequence_number,
        item_id=build_response_message_id(response_id=response_id),
        output_index=output_index,
        content_index=content_index,
        part=OpenAIResponsesOutputText(text=''),
    )


def build_openai_responses_content_part_done_event(
    *,
    response_id: str,
    text: str,
    sequence_number: int,
    output_index: int = 0,
    content_index: int = 0,
) -> OpenAIResponsesContentPartDoneEvent:
    """Build one ``response.content_part.done`` event for a response stream."""
    return OpenAIResponsesContentPartDoneEvent(
        sequence_number=sequence_number,
        item_id=build_response_message_id(response_id=response_id),
        output_index=output_index,
        content_index=content_index,
        part=OpenAIResponsesOutputText(text=text),
    )


def build_openai_responses_output_item_added_event(
    *,
    item: OpenAIResponsesOutputItem,
    sequence_number: int,
    output_index: int = 0,
) -> OpenAIResponsesOutputItemAddedEvent:
    """Build one ``response.output_item.added`` event for a response stream."""
    return OpenAIResponsesOutputItemAddedEvent(
        sequence_number=sequence_number,
        output_index=output_index,
        item=item,
    )


def build_openai_responses_output_item_done_event(
    *,
    item: OpenAIResponsesOutputItem,
    sequence_number: int,
    output_index: int = 0,
) -> OpenAIResponsesOutputItemDoneEvent:
    """Build one ``response.output_item.done`` event for a response stream."""
    return OpenAIResponsesOutputItemDoneEvent(
        sequence_number=sequence_number,
        output_index=output_index,
        item=item,
    )


def build_openai_responses_output_message(
    *,
    response_id: str,
    output_text: str,
    status: Literal['in_progress', 'completed'],
) -> OpenAIResponsesOutputMessage:
    """Build a single assistant output message for a Responses payload."""
    return OpenAIResponsesOutputMessage(
        id=build_response_message_id(response_id=response_id),
        status=status,
        content=[OpenAIResponsesOutputText(text=output_text)],
    )


def build_openai_responses_function_call_item(
    *,
    response_id: str,
    tool_call: CanonicalToolCall,
) -> OpenAIResponsesFunctionCall:
    """Build a function-call output item for one pending tool request."""
    return OpenAIResponsesFunctionCall(
        id=f'{build_response_message_id(response_id=response_id)}_tool_{tool_call.call_id}',
        call_id=tool_call.call_id,
        name=tool_call.name,
        arguments=_serialize_tool_arguments(arguments=tool_call.arguments),
    )


def _normalize_responses_message_block(
    *,
    value: str | list[OpenAIResponsesInputMessage],
    default_role: Literal['system', 'user'],
) -> list[CanonicalChatMessage]:
    """Normalize a Responses message block into canonical chat messages."""
    if isinstance(value, str):
        return [CanonicalChatMessage(role=default_role, content=value)]

    normalized_messages: list[CanonicalChatMessage] = []
    for item in value:
        normalized_messages.extend(_normalize_responses_message_item(item=item))

    return normalized_messages


def _normalize_responses_message_item(
    *,
    item: OpenAIResponsesInputMessage,
) -> list[CanonicalChatMessage]:
    """Normalize one structured Responses message item."""
    normalized_role = 'system' if item.role in {'system', 'developer'} else item.role
    return _normalize_responses_message_content(
        role=cast("Literal['system', 'user', 'assistant']", normalized_role),
        content=item.content,
    )


def _normalize_responses_message_content(
    *,
    role: Literal['system', 'user', 'assistant'],
    content: str | list[OpenAIResponsesInputContentPart],
) -> list[CanonicalChatMessage]:
    """Normalize one Responses message content payload."""
    if isinstance(content, str):
        return [CanonicalChatMessage(role=role, content=content)]

    return [
        CanonicalChatMessage(role=role, content=part.text)
        for part in content
        if isinstance(part.text, str) and part.text
    ]


def _normalize_openai_responses_input(
    *,
    instructions: str | list[OpenAIResponsesInputMessage] | None,
    input_value: str
    | list[
        OpenAIResponsesInputMessage
        | OpenAIResponsesFunctionCallReplayItem
        | OpenAIResponsesFunctionCallOutputItem
    ],
) -> tuple[list[CanonicalChatMessage], list[CanonicalToolResult]]:
    """Normalize the full Responses input payload into canonical messages and results."""
    messages: list[CanonicalChatMessage] = []
    tool_results: list[CanonicalToolResult] = []

    if instructions is not None:
        messages.extend(
            _normalize_responses_message_block(
                value=instructions,
                default_role='system',
            )
        )

    if isinstance(input_value, str):
        messages.extend(
            _normalize_responses_message_block(value=input_value, default_role='user')
        )
        return messages, tool_results

    for item in input_value:
        if isinstance(item, OpenAIResponsesInputMessage):
            messages.extend(_normalize_responses_message_item(item=item))
            continue
        if isinstance(item, OpenAIResponsesFunctionCallReplayItem):
            continue

        tool_results.append(
            CanonicalToolResult(
                call_id=item.call_id,
                output_text=_normalize_tool_result_output_text(output=item.output),
            )
        )

    return messages, tool_results


def _normalize_openai_tool_definitions(
    *,
    tools: list[dict[str, Any]],
) -> list[CanonicalToolDefinition]:
    """Normalize OpenAI tool definitions into the canonical tool contract."""
    normalized_tools: list[CanonicalToolDefinition] = []
    for tool in tools:
        normalized_tool = _normalize_openai_tool_definition(tool=tool)
        if normalized_tool is not None:
            normalized_tools.append(normalized_tool)

    return normalized_tools


def _normalize_openai_tool_definition(
    *,
    tool: dict[str, Any],
) -> CanonicalToolDefinition | None:
    """Normalize one OpenAI Responses tool into the canonical tool contract."""
    tool_type = tool.get('type')
    if tool_type == 'web_search':
        return _build_openai_web_search_tool_definition(tool=tool)
    if tool_type == 'custom':
        return _build_openai_custom_tool_definition(tool=tool)
    if tool_type not in {None, 'function'}:
        return None

    return _build_openai_function_tool_definition(tool=tool)


def _normalize_openai_response_tools(
    *, tools: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return the response-visible tool list after provider-side normalization."""
    normalized_tools: list[dict[str, Any]] = []
    for tool in tools:
        if tool.get('type') == 'web_search':
            normalized_tools.append(
                {
                    'type': 'function',
                    'name': 'web_search',
                    'description': _resolve_openai_web_search_description(tool=tool),
                    'parameters': _build_openai_web_search_parameters(),
                }
            )
            continue
        normalized_tools.append(tool)
    return normalized_tools


def _build_openai_web_search_tool_definition(
    *, tool: dict[str, Any]
) -> CanonicalToolDefinition:
    """Build the canonical tool definition for one Responses web-search tool."""
    return CanonicalToolDefinition(
        name='web_search',
        description=_resolve_openai_web_search_description(tool=tool),
        parameters=_build_openai_web_search_parameters(),
    )


def _build_openai_custom_tool_definition(
    *, tool: dict[str, Any]
) -> CanonicalToolDefinition | None:
    """Build a canonical external-tool definition for one Responses custom tool."""
    name = tool.get('name')
    if not isinstance(name, str) or not name.strip():
        return None
    description = tool.get('description')
    return CanonicalToolDefinition(
        name=name.strip(),
        description=description if isinstance(description, str) else '',
    )


def _build_openai_function_tool_definition(
    *,
    tool: dict[str, Any],
) -> CanonicalToolDefinition | None:
    """Build the canonical tool definition for one Responses function tool."""
    function_payload = tool.get('function')
    if isinstance(function_payload, dict):
        typed_function_payload = cast('dict[str, Any]', function_payload)
        name: object = typed_function_payload.get('name')
        description: object = typed_function_payload.get('description') or ''
        parameters: object = typed_function_payload.get('parameters')
    else:
        name = tool.get('name')
        description = tool.get('description') or ''
        parameters = tool.get('parameters')

    if not isinstance(name, str) or not name.strip():
        return None

    return CanonicalToolDefinition(
        name=name.strip(),
        description=description if isinstance(description, str) else '',
        parameters=(
            cast('dict[str, Any]', parameters) if isinstance(parameters, dict) else None
        ),
    )


def _resolve_openai_web_search_description(*, tool: dict[str, Any]) -> str:
    """Return the provider-visible description for one Responses web-search tool."""
    description = tool.get('description')
    if isinstance(description, str) and description.strip():
        return description
    return 'Search the web for recent information and official sources.'


def _build_openai_web_search_parameters() -> dict[str, Any]:
    """Return the canonical JSON schema used for one Responses web-search tool."""
    return {
        'type': 'object',
        'properties': {
            'query': {
                'type': 'string',
                'description': 'Search query.',
            }
        },
        'required': ['query'],
        'additionalProperties': False,
    }


def _normalize_tool_result_output_text(*, output: object) -> str:
    """Normalize a Responses function-call output payload into tool-result text."""
    return _serialize_responses_value(value=output)


def _serialize_tool_arguments(*, arguments: object) -> str:
    """Serialize tool arguments for the OpenAI Responses function-call item."""
    return _serialize_responses_value(value=arguments)


def _serialize_responses_value(*, value: object) -> str:
    """Serialize one Responses payload value into the wire-format string form."""
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))
