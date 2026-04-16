"""Unit tests for the Copilot SDK-backed runtime."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, cast

import pytest
from copilot import CopilotClient, SubprocessConfig
from copilot.generated.session_events import PermissionRequest, SessionEvent
from copilot.tools import ToolInvocation

from copilot_model_provider.core.errors import ProviderError
from copilot_model_provider.core.models import (
    CanonicalChatMessage,
    CanonicalChatRequest,
    CanonicalToolDefinition,
    CanonicalToolResult,
    ResolvedRoute,
    RuntimeDiscoveredModel,
    derive_tool_routing_policy,
)
from copilot_model_provider.runtimes.copilot_runtime import (
    CopilotRuntime,
    PermissionRequestHandler,
)


@dataclass
class _FakeEventData:
    """Minimal fake event payload matching the runtime read path."""

    content: str | None
    message_id: str | None = None
    input_tokens: int | float | str | None = None
    output_tokens: int | float | str | None = None


@dataclass
class _FakeEvent:
    """Minimal fake event wrapper matching the runtime read path."""

    data: _FakeEventData | None
    type: str = 'assistant.message'


@dataclass
class _FakeListedModel:
    """Minimal fake model descriptor matching the runtime discovery path."""

    id: str
    name: str | None = None
    capabilities: object | None = None
    policy: object | None = None
    billing: object | None = None
    supported_reasoning_efforts: list[str] | None = None
    default_reasoning_effort: str | None = None


@dataclass
class _FakeListedModelSupports:
    """Minimal fake capability-support flags for runtime discovery tests."""

    vision: bool | None = None
    reasoning_effort: bool | None = None


@dataclass
class _FakeListedModelVisionLimits:
    """Minimal fake vision limits for runtime discovery tests."""

    supported_media_types: list[str] | None = None
    max_prompt_images: int | None = None
    max_prompt_image_size: int | None = None


@dataclass
class _FakeListedModelLimits:
    """Minimal fake limit metadata for runtime discovery tests."""

    max_prompt_tokens: int | None = None
    max_context_window_tokens: int | None = None
    vision: _FakeListedModelVisionLimits | None = None


@dataclass
class _FakeListedModelCapabilities:
    """Minimal fake capability metadata for runtime discovery tests."""

    supports: _FakeListedModelSupports | None = None
    limits: _FakeListedModelLimits | None = None


@dataclass
class _FakeListedModelPolicy:
    """Minimal fake policy metadata for runtime discovery tests."""

    state: str | None = None
    terms: str | None = None


@dataclass
class _FakeListedModelBilling:
    """Minimal fake billing metadata for runtime discovery tests."""

    multiplier: float | None = None


class _FakeSession:
    """Deterministic fake Copilot session for runtime tests."""

    def __init__(
        self,
        *,
        session_id: str = 'copilot-session-1',
        event: _FakeEvent | None = None,
        stream_events: list[Any] | None = None,
        stream_event_batches: list[list[Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        """Store the fake completion behavior for later execution."""
        self.session_id = session_id
        self._event = event
        self._stream_events = stream_events or []
        self._stream_event_batches = stream_event_batches or []
        self._error = error
        self.prompt: str | None = None
        self.sent_prompts: list[str] = []
        self.timeout: float | None = None
        self.disconnected = False
        self._handlers: list[Any] = []
        self._on_event: Any = None

    async def send(
        self,
        prompt: str,
        *,
        attachments: list[object] | None = None,
        mode: str | None = None,
    ) -> str:
        """Record a streaming send and dispatch configured fake stream events."""
        del attachments, mode
        self.prompt = prompt
        self.sent_prompts.append(prompt)
        if self._error is not None:
            raise self._error

        stream_events = (
            self._stream_event_batches.pop(0)
            if self._stream_event_batches
            else self._stream_events
        )
        for event in stream_events:
            if self._on_event is not None:
                self._on_event(event)
            for handler in list(self._handlers):
                handler(event)

        return 'message-1'

    async def send_and_wait(
        self,
        prompt: str,
        *,
        attachments: list[object] | None = None,
        mode: str | None = None,
        timeout: float = 60.0,  # noqa: ASYNC109 - mirrors SDK signature
    ) -> _FakeEvent | None:
        """Record the prompt and either raise or return the configured event."""
        del attachments, mode
        self.prompt = prompt
        self.timeout = timeout
        if self._error is not None:
            raise self._error

        return self._event

    def on(self, handler: Any) -> Any:
        """Register a fake event handler and return an unsubscribe function."""
        self._handlers.append(handler)

        def _unsubscribe() -> None:
            self._handlers.remove(handler)

        return _unsubscribe

    async def disconnect(self) -> None:
        """Track that the runtime tears the session down after each request."""
        self.disconnected = True


class _FakeClient:
    """Deterministic fake Copilot client for runtime tests."""

    def __init__(
        self,
        *,
        session: _FakeSession,
        state: str = 'disconnected',
        listed_models: list[_FakeListedModel] | None = None,
    ) -> None:
        """Store the fake session and initial lifecycle state."""
        self._session = session
        self._state = state
        self._listed_models = listed_models or []
        self.started = False
        self.stopped = False
        self.create_session_calls: list[dict[str, Any]] = []

    def get_state(self) -> str:
        """Return the current fake lifecycle state."""
        return self._state

    async def start(self) -> None:
        """Simulate connecting the underlying Copilot client."""
        self.started = True
        self._state = 'connected'

    async def stop(self) -> None:
        """Simulate stopping the underlying Copilot client."""
        self.stopped = True
        self._state = 'disconnected'

    async def create_session(
        self,
        *,
        on_permission_request: PermissionRequestHandler,
        model: str | None = None,
        excluded_tools: list[str] | None = None,
        working_directory: str | None = None,
        streaming: bool | None = None,
        on_event: Any = None,
        tools: list[Any] | None = None,
    ) -> _FakeSession:
        """Record session creation arguments and return the fake session."""
        self._session._on_event = on_event
        self.create_session_calls.append(
            {
                'on_permission_request': on_permission_request,
                'model': model,
                'excluded_tools': excluded_tools,
                'working_directory': working_directory,
                'streaming': streaming,
                'on_event': on_event,
                'tools': tools,
            }
        )
        return self._session

    async def list_models(self) -> list[_FakeListedModel]:
        """Return the configured fake live-model list."""
        return self._listed_models


def _build_request(
    *,
    runtime_auth_token: str | None = None,
    stream: bool = False,
) -> CanonicalChatRequest:
    """Construct a stable canonical request used by runtime tests."""
    return CanonicalChatRequest(
        runtime_auth_token=runtime_auth_token,
        model_id='gpt-5.4',
        messages=[CanonicalChatMessage(role='user', content='Hello')],
        stream=stream,
    )


def _build_read_file_tool_definition() -> CanonicalToolDefinition:
    """Construct the canonical read-file tool definition used in tool-loop tests."""
    return CanonicalToolDefinition(
        name='read_file',
        description='Read a file.',
        parameters={'type': 'object'},
    )


def _build_read_file_tool_result(
    *,
    output_text: str = 'README contents',
    is_error: bool = False,
    error_text: str | None = None,
) -> CanonicalToolResult:
    """Construct the canonical read-file tool result used in tool-loop tests."""
    return CanonicalToolResult(
        call_id='call_readme',
        output_text=output_text,
        is_error=is_error,
        error_text=error_text,
    )


def _build_tool_aware_request(
    *,
    session_id: str | None = None,
    messages: list[CanonicalChatMessage] | None = None,
    tool_definitions: list[CanonicalToolDefinition] | None = None,
    tool_results: list[CanonicalToolResult] | None = None,
    stream: bool = False,
) -> CanonicalChatRequest:
    """Construct a stable tool-aware request used by interactive runtime tests."""
    resolved_messages = messages or [
        CanonicalChatMessage(role='user', content='Hello'),
    ]
    resolved_tool_definitions = tool_definitions or [_build_read_file_tool_definition()]
    resolved_tool_results = tool_results or []

    return CanonicalChatRequest(
        model_id='gpt-5.4',
        session_id=session_id,
        messages=resolved_messages,
        tool_definitions=resolved_tool_definitions,
        tool_results=resolved_tool_results,
        tool_routing_policy=derive_tool_routing_policy(
            surface='openai_responses',
            session_id=session_id,
            tool_definitions=resolved_tool_definitions,
            tool_results=resolved_tool_results,
        ),
        stream=stream,
    )


def _build_interactive_session_state(
    *,
    session: _FakeSession | None = None,
) -> CopilotRuntime._InteractiveCopilotSession:
    """Construct interactive session state with the deterministic fake session."""
    resolved_session = session or _FakeSession(session_id='copilot-session-tool')
    return CopilotRuntime._InteractiveCopilotSession(
        active_session=CopilotRuntime._ActiveCopilotSession(
            session=cast('Any', resolved_session),
            client=CopilotRuntime._ResolvedCopilotClient(
                client=cast('CopilotClient', _FakeClient(session=_FakeSession()))
            ),
        ),
        event_queue=asyncio.Queue(),
        pending_tool_calls={},
    )


@pytest.mark.asyncio
async def test_copilot_runtime_executes_and_translates_completion() -> None:
    """Verify that the runtime starts the client, sends the prompt, and tears down."""
    session = _FakeSession(
        event=_FakeEvent(
            data=_FakeEventData(
                content='Hi from Copilot',
                message_id='chatcmpl-fake',
                input_tokens=12,
                output_tokens=5,
            )
        )
    )
    client = _FakeClient(session=session)
    runtime = CopilotRuntime(
        client_factory=lambda: cast('CopilotClient', client),
        timeout_seconds=15.0,
        working_directory='/workspace',
    )

    completion = await runtime.complete_chat(
        request=_build_request(),
        route=ResolvedRoute(
            runtime='copilot',
            runtime_model_id='copilot-default',
        ),
    )

    assert client.started is True
    assert session.disconnected is True
    assert session.timeout == 15.0
    assert session.prompt == 'User: Hello\n\nAssistant:'
    assert len(client.create_session_calls) == 1
    create_session_call = client.create_session_calls[0]
    assert create_session_call['model'] == 'copilot-default'
    assert create_session_call['working_directory'] == '/workspace'
    assert create_session_call['streaming'] is False
    assert callable(create_session_call['on_permission_request'])
    assert completion.output_text == 'Hi from Copilot'
    assert completion.provider_response_id == 'chatcmpl-fake'
    assert completion.session_id == 'copilot-session-1'
    assert completion.prompt_tokens == 12
    assert completion.completion_tokens == 5


def test_copilot_runtime_defaults_to_subprocess_mode() -> None:
    """Verify that the runtime reports subprocess mode."""
    runtime = CopilotRuntime()

    assert runtime.connection_mode == 'subprocess'


def test_copilot_runtime_builds_default_client_without_external_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that the default client uses the SDK default configuration."""
    captured_arguments: dict[str, object] = {}

    class _CapturedClient:
        """Capture constructor arguments for the default client factory."""

        def __init__(
            self,
            config: object = None,
            *,
            auto_start: bool = True,
        ) -> None:
            """Record the configuration passed to the SDK client."""
            captured_arguments['config'] = config
            captured_arguments['auto_start'] = auto_start

    monkeypatch.setattr(
        'copilot_model_provider.runtimes.copilot_runtime.CopilotClient',
        _CapturedClient,
    )

    runtime = CopilotRuntime()
    runtime._get_or_create_client()

    assert captured_arguments['config'] is None
    assert captured_arguments['auto_start'] is False


def test_copilot_runtime_builds_authenticated_subprocess_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that authenticated clients use subprocess mode with github_token."""
    captured_arguments: dict[str, object] = {}

    class _CapturedClient:
        """Capture constructor arguments for authenticated client creation."""

        def __init__(
            self,
            config: object = None,
            *,
            auto_start: bool = True,
        ) -> None:
            """Record the configuration passed to the SDK client."""
            captured_arguments['config'] = config
            captured_arguments['auto_start'] = auto_start

    monkeypatch.setattr(
        'copilot_model_provider.runtimes.copilot_runtime.CopilotClient',
        _CapturedClient,
    )

    runtime = CopilotRuntime(working_directory='/workspace')
    runtime._build_authenticated_client('github-token-123')

    config = cast('SubprocessConfig', captured_arguments['config'])
    assert isinstance(config, SubprocessConfig)
    assert config.github_token == 'github-token-123'  # noqa: S105 - deterministic test token
    assert config.cwd == '/workspace'
    assert captured_arguments['auto_start'] is False


@pytest.mark.asyncio
async def test_copilot_runtime_uses_authenticated_client_factory_for_bearer_tokens() -> (
    None
):
    """Verify that bearer-token requests use a short-lived authenticated client."""
    default_client = _FakeClient(session=_FakeSession())
    authed_session = _FakeSession(
        event=_FakeEvent(data=_FakeEventData(content='Hi from authed client'))
    )
    authed_client = _FakeClient(session=authed_session)
    captured_tokens: list[str] = []
    runtime = CopilotRuntime(
        client_factory=lambda: cast('CopilotClient', default_client),
        authenticated_client_factory=lambda token: (
            captured_tokens.append(token) or cast('CopilotClient', authed_client)
        ),
    )

    completion = await runtime.complete_chat(
        request=_build_request(
            runtime_auth_token='github-token-123',  # noqa: S106 - deterministic test token
        ),
        route=ResolvedRoute(
            runtime='copilot',
            runtime_model_id='copilot-default',
        ),
    )

    assert captured_tokens == ['github-token-123']
    assert default_client.started is False
    assert authed_client.started is True
    assert authed_client.stopped is True
    assert completion.output_text == 'Hi from authed client'


@pytest.mark.asyncio
async def test_copilot_runtime_lists_live_model_ids_from_default_client() -> None:
    """Verify that model discovery uses the shared default client by default."""
    client = _FakeClient(
        session=_FakeSession(),
        listed_models=[
            _FakeListedModel(id='gpt-5.4'),
            _FakeListedModel(id='gpt-5.4-mini'),
            _FakeListedModel(id='gpt-5.4'),
        ],
    )
    runtime = CopilotRuntime(client_factory=lambda: cast('CopilotClient', client))

    model_ids = await runtime.list_model_ids()

    assert model_ids == ('gpt-5.4', 'gpt-5.4-mini')
    assert client.started is True
    assert client.stopped is False


@pytest.mark.asyncio
async def test_copilot_runtime_list_models_preserves_runtime_metadata() -> None:
    """Verify that rich runtime discovery metadata is preserved internally."""
    client = _FakeClient(
        session=_FakeSession(),
        listed_models=[
            _FakeListedModel(
                id='claude-opus-4.6-1m',
                name='Claude Opus 4.6 (1M context)(Internal only)',
                capabilities=_FakeListedModelCapabilities(
                    supports=_FakeListedModelSupports(
                        vision=True,
                        reasoning_effort=True,
                    ),
                    limits=_FakeListedModelLimits(
                        max_prompt_tokens=936000,
                        max_context_window_tokens=1000000,
                        vision=_FakeListedModelVisionLimits(
                            supported_media_types=['image/png', 'image/jpeg'],
                            max_prompt_images=20,
                            max_prompt_image_size=5_242_880,
                        ),
                    ),
                ),
                policy=_FakeListedModelPolicy(
                    state='enabled', terms='internal-preview'
                ),
                billing=_FakeListedModelBilling(multiplier=1.5),
                supported_reasoning_efforts=['low', 'medium', 'high'],
                default_reasoning_effort='medium',
            )
        ],
    )
    runtime = CopilotRuntime(client_factory=lambda: cast('CopilotClient', client))

    models = await runtime.list_models()

    assert models == (
        RuntimeDiscoveredModel.model_validate(
            {
                'id': 'claude-opus-4.6-1m',
                'copilot': {
                    'name': 'Claude Opus 4.6 (1M context)(Internal only)',
                    'capabilities': {
                        'supports': {
                            'vision': True,
                            'reasoning_effort': True,
                        },
                        'limits': {
                            'max_prompt_tokens': 936000,
                            'max_context_window_tokens': 1000000,
                            'vision': {
                                'supported_media_types': [
                                    'image/png',
                                    'image/jpeg',
                                ],
                                'max_prompt_images': 20,
                                'max_prompt_image_size': 5_242_880,
                            },
                        },
                    },
                    'policy': {
                        'state': 'enabled',
                        'terms': 'internal-preview',
                    },
                    'billing': {'multiplier': 1.5},
                    'supported_reasoning_efforts': ['low', 'medium', 'high'],
                    'default_reasoning_effort': 'medium',
                },
            }
        ),
    )
    assert client.started is True
    assert client.stopped is False


@pytest.mark.asyncio
async def test_copilot_runtime_lists_live_model_ids_with_authenticated_client() -> None:
    """Verify that auth-scoped model discovery uses a short-lived client."""
    default_client = _FakeClient(session=_FakeSession())
    authed_client = _FakeClient(
        session=_FakeSession(),
        listed_models=[_FakeListedModel(id='gpt-5.4')],
    )
    captured_tokens: list[str] = []
    runtime = CopilotRuntime(
        client_factory=lambda: cast('CopilotClient', default_client),
        authenticated_client_factory=lambda token: (
            captured_tokens.append(token) or cast('CopilotClient', authed_client)
        ),
    )

    model_ids = await runtime.list_model_ids(
        runtime_auth_token='github-token-123'  # noqa: S106 - deterministic test token
    )

    assert model_ids == ('gpt-5.4',)
    assert captured_tokens == ['github-token-123']
    assert default_client.started is False
    assert authed_client.started is True
    assert authed_client.stopped is True


def test_copilot_runtime_denies_runtime_permission_requests() -> None:
    """Verify that the thin provider denies server-side permission requests."""
    runtime = CopilotRuntime()
    result = runtime._deny_permission_request(
        PermissionRequest.from_dict({'kind': 'custom-tool', 'toolName': 'bash'}),
        {},
    )

    assert result.kind == 'denied-by-rules'
    assert 'disabled' in cast('str', result.message)


@pytest.mark.asyncio
async def test_copilot_runtime_raises_when_runtime_returns_no_content() -> None:
    """Verify that empty assistant messages become structured provider failures."""
    session = _FakeSession(event=_FakeEvent(data=_FakeEventData(content=None)))
    runtime = CopilotRuntime(
        client_factory=lambda: cast('CopilotClient', _FakeClient(session=session))
    )

    with pytest.raises(ProviderError, match='Copilot runtime returned no assistant'):
        await runtime.complete_chat(
            request=_build_request(),
            route=ResolvedRoute(
                runtime='copilot',
                runtime_model_id='copilot-default',
            ),
        )


@pytest.mark.asyncio
async def test_copilot_runtime_raises_when_runtime_returns_no_event_data() -> None:
    """Verify that missing event data becomes a structured provider failure."""
    session = _FakeSession(event=_FakeEvent(data=None))
    runtime = CopilotRuntime(
        client_factory=lambda: cast('CopilotClient', _FakeClient(session=session))
    )

    with pytest.raises(ProviderError, match='Copilot runtime returned no assistant'):
        await runtime.complete_chat(
            request=_build_request(),
            route=ResolvedRoute(
                runtime='copilot',
                runtime_model_id='copilot-default',
            ),
        )


@pytest.mark.asyncio
async def test_copilot_runtime_raises_when_token_metadata_is_invalid() -> None:
    """Verify that malformed token metadata is normalized into ProviderError."""
    session = _FakeSession(
        event=_FakeEvent(
            data=_FakeEventData(
                content='Hi from Copilot',
                input_tokens='not-a-number',
                output_tokens=5,
            )
        )
    )
    runtime = CopilotRuntime(
        client_factory=lambda: cast('CopilotClient', _FakeClient(session=session))
    )

    with pytest.raises(ProviderError, match='invalid token metadata'):
        await runtime.complete_chat(
            request=_build_request(),
            route=ResolvedRoute(
                runtime='copilot',
                runtime_model_id='copilot-default',
            ),
        )


@pytest.mark.asyncio
async def test_copilot_runtime_streams_events_and_keeps_session_id() -> None:
    """Verify that streaming execution yields ordered events and session metadata."""
    session = _FakeSession(
        session_id='copilot-session-stream',
        stream_events=[
            SessionEvent.from_dict(
                {
                    'id': '00000000-0000-0000-0000-000000000021',
                    'timestamp': '2025-01-01T00:00:00Z',
                    'type': 'assistant.message_delta',
                    'data': {'deltaContent': 'Hello'},
                }
            ),
            SessionEvent.from_dict(
                {
                    'id': '00000000-0000-0000-0000-000000000022',
                    'timestamp': '2025-01-01T00:00:00Z',
                    'type': 'assistant.turn_end',
                    'data': {'reason': 'stop'},
                }
            ),
        ],
    )
    client = _FakeClient(session=session)
    runtime = CopilotRuntime(client_factory=lambda: cast('CopilotClient', client))

    runtime_stream = await runtime.stream_chat(
        request=_build_request(stream=True),
        route=ResolvedRoute(
            runtime='copilot',
            runtime_model_id='copilot-default',
        ),
    )
    events = [event async for event in runtime_stream.events]

    assert runtime_stream.session_id == 'copilot-session-stream'
    assert [event.type.value for event in events] == [
        'assistant.message_delta',
        'assistant.turn_end',
    ]
    assert session.prompt == 'User: Hello\n\nAssistant:'
    assert session.disconnected is True


@pytest.mark.asyncio
async def test_copilot_runtime_completes_interactive_turn_with_pending_tool_calls() -> (
    None
):
    """Verify that tool-aware turns preserve session state and surface tool calls."""
    session = _FakeSession(
        session_id='copilot-session-tool',
        stream_events=[
            SessionEvent.from_dict(
                {
                    'id': '30000000-0000-0000-0000-000000000001',
                    'timestamp': '2025-01-01T00:00:00Z',
                    'type': 'assistant.message_delta',
                    'data': {'deltaContent': 'Plan'},
                }
            ),
            SessionEvent.from_dict(
                {
                    'id': '30000000-0000-0000-0000-000000000002',
                    'timestamp': '2025-01-01T00:00:00Z',
                    'type': 'assistant.usage',
                    'data': {'inputTokens': 11, 'outputTokens': 3},
                }
            ),
            SessionEvent.from_dict(
                {
                    'id': '30000000-0000-0000-0000-000000000003',
                    'timestamp': '2025-01-01T00:00:00Z',
                    'type': 'external_tool.requested',
                    'data': {
                        'requestId': 'tool-request-1',
                        'toolName': 'read_file',
                        'toolCallId': 'call_readme',
                        'arguments': {'path': 'README.md'},
                    },
                }
            ),
        ],
    )
    client = _FakeClient(session=session)
    runtime = CopilotRuntime(client_factory=lambda: cast('CopilotClient', client))

    completion = await runtime.complete_chat(
        request=_build_tool_aware_request(),
        route=ResolvedRoute(runtime='copilot', runtime_model_id='copilot-default'),
    )

    assert completion.output_text == 'Plan'
    assert completion.finish_reason == 'tool_calls'
    assert completion.session_id == 'copilot-session-tool'
    assert completion.prompt_tokens == 11
    assert completion.completion_tokens == 3
    assert len(completion.pending_tool_calls) == 1
    assert completion.pending_tool_calls[0].call_id == 'call_readme'
    assert completion.pending_tool_calls[0].name == 'read_file'
    assert completion.pending_tool_calls[0].arguments == {'path': 'README.md'}
    assert len(client.create_session_calls) == 1
    create_session_call = client.create_session_calls[0]
    assert create_session_call['excluded_tools'] == ['web_search', 'web_fetch']
    assert create_session_call['streaming'] is True
    assert create_session_call['tools'] is not None
    assert len(cast('list[Any]', create_session_call['tools'])) == 1
    assert 'external or MCP tools' in cast('str', session.prompt)
    assert cast('str', session.prompt).endswith('User: Hello\n\nAssistant:')
    assert session.disconnected is False
    assert 'copilot-session-tool' in runtime._interactive_sessions

    await runtime._discard_interactive_session(
        session_id='copilot-session-tool',
        disconnect=True,
    )

    assert session.disconnected is True
    assert 'copilot-session-tool' not in runtime._interactive_sessions


@pytest.mark.asyncio
async def test_copilot_runtime_batches_multiple_tool_requests_in_one_turn() -> None:
    """Verify that one interactive turn can surface multiple pending tool calls."""
    session = _FakeSession(
        session_id='copilot-session-tool-batch',
        stream_events=[
            SessionEvent.from_dict(
                {
                    'id': '30000000-0000-0000-0000-000000000101',
                    'timestamp': '2025-01-01T00:00:00Z',
                    'type': 'assistant.message_delta',
                    'data': {'deltaContent': 'Plan'},
                }
            ),
            SessionEvent.from_dict(
                {
                    'id': '30000000-0000-0000-0000-000000000102',
                    'timestamp': '2025-01-01T00:00:00Z',
                    'type': 'external_tool.requested',
                    'data': {
                        'requestId': 'tool-request-1',
                        'toolName': 'read_file',
                        'toolCallId': 'call_readme',
                        'arguments': {'path': 'README.md'},
                    },
                }
            ),
            SessionEvent.from_dict(
                {
                    'id': '30000000-0000-0000-0000-000000000103',
                    'timestamp': '2025-01-01T00:00:00Z',
                    'type': 'external_tool.requested',
                    'data': {
                        'requestId': 'tool-request-2',
                        'toolName': 'list_dir',
                        'toolCallId': 'call_docs',
                        'arguments': {'path': 'docs'},
                    },
                }
            ),
            SessionEvent.from_dict(
                {
                    'id': '30000000-0000-0000-0000-000000000104',
                    'timestamp': '2025-01-01T00:00:00Z',
                    'type': 'assistant.turn_end',
                    'data': {
                        'reason': 'tool_calls',
                        'inputTokens': 14,
                        'outputTokens': 4,
                    },
                }
            ),
        ],
    )
    runtime = CopilotRuntime(
        client_factory=lambda: cast('CopilotClient', _FakeClient(session=session))
    )

    completion = await runtime.complete_chat(
        request=_build_tool_aware_request(),
        route=ResolvedRoute(runtime='copilot', runtime_model_id='copilot-default'),
    )

    assert completion.output_text == 'Plan'
    assert completion.finish_reason == 'tool_calls'
    assert completion.session_id == 'copilot-session-tool-batch'
    assert completion.prompt_tokens == 14
    assert completion.completion_tokens == 4
    assert [tool_call.call_id for tool_call in completion.pending_tool_calls] == [
        'call_readme',
        'call_docs',
    ]
    assert [tool_call.name for tool_call in completion.pending_tool_calls] == [
        'read_file',
        'list_dir',
    ]
    assert 'copilot-session-tool-batch' in runtime._interactive_sessions

    await runtime._discard_interactive_session(
        session_id='copilot-session-tool-batch',
        disconnect=True,
    )

    assert session.disconnected is True


@pytest.mark.asyncio
async def test_copilot_runtime_deduplicates_replayed_tool_requests_in_one_turn() -> (
    None
):
    """Verify that aggregate assistant tool metadata does not duplicate live tool calls."""
    session = _FakeSession(
        session_id='copilot-session-tool-dedupe',
        stream_events=[
            SessionEvent.from_dict(
                {
                    'id': '30000000-0000-0000-0000-000000000201',
                    'timestamp': '2025-01-01T00:00:00Z',
                    'type': 'external_tool.requested',
                    'data': {
                        'requestId': 'tool-request-1',
                        'toolName': 'report_intent',
                        'toolCallId': 'call_intent',
                        'arguments': {'intent': 'Reading README.md'},
                    },
                }
            ),
            SessionEvent.from_dict(
                {
                    'id': '30000000-0000-0000-0000-000000000202',
                    'timestamp': '2025-01-01T00:00:00Z',
                    'type': 'external_tool.requested',
                    'data': {
                        'requestId': 'tool-request-2',
                        'toolName': 'read_file',
                        'toolCallId': 'call_readme',
                        'arguments': {'path': 'README.md'},
                    },
                }
            ),
            SessionEvent.from_dict(
                {
                    'id': '30000000-0000-0000-0000-000000000203',
                    'timestamp': '2025-01-01T00:00:00Z',
                    'type': 'assistant.message',
                    'data': {
                        'content': 'Whole message',
                        'toolRequests': [
                            {
                                'toolCallId': 'call_intent',
                                'name': 'report_intent',
                                'arguments': {'intent': 'Reading README.md'},
                            },
                            {
                                'toolCallId': 'call_readme',
                                'name': 'read_file',
                                'arguments': {'path': 'README.md'},
                            },
                        ],
                    },
                }
            ),
            SessionEvent.from_dict(
                {
                    'id': '30000000-0000-0000-0000-000000000204',
                    'timestamp': '2025-01-01T00:00:00Z',
                    'type': 'assistant.turn_end',
                    'data': {
                        'reason': 'tool_calls',
                        'inputTokens': 14,
                        'outputTokens': 4,
                    },
                }
            ),
        ],
    )
    runtime = CopilotRuntime(
        client_factory=lambda: cast('CopilotClient', _FakeClient(session=session))
    )

    completion = await runtime.complete_chat(
        request=_build_tool_aware_request(),
        route=ResolvedRoute(runtime='copilot', runtime_model_id='copilot-default'),
    )

    assert [tool_call.call_id for tool_call in completion.pending_tool_calls] == [
        'call_intent',
        'call_readme',
    ]
    assert [tool_call.name for tool_call in completion.pending_tool_calls] == [
        'report_intent',
        'read_file',
    ]

    await runtime._discard_interactive_session(
        session_id='copilot-session-tool-dedupe',
        disconnect=True,
    )


@pytest.mark.asyncio
async def test_copilot_runtime_interactive_stream_closes_terminal_turns() -> None:
    """Verify that terminal interactive turns are discarded after streaming ends."""
    session = _FakeSession(
        session_id='copilot-session-finished',
        stream_events=[
            SessionEvent.from_dict(
                {
                    'id': '30000000-0000-0000-0000-000000000011',
                    'timestamp': '2025-01-01T00:00:00Z',
                    'type': 'assistant.turn_end',
                    'data': {'reason': 'stop'},
                }
            )
        ],
    )
    runtime = CopilotRuntime(
        client_factory=lambda: cast('CopilotClient', _FakeClient(session=session))
    )

    runtime_stream = await runtime.stream_chat(
        request=_build_tool_aware_request(stream=True),
        route=ResolvedRoute(runtime='copilot', runtime_model_id='copilot-default'),
    )
    events = [event async for event in runtime_stream.events]

    assert runtime_stream.session_id == 'copilot-session-finished'
    assert [event.type.value for event in events] == ['assistant.turn_end']
    assert session.disconnected is True
    assert runtime._interactive_sessions == {}


@pytest.mark.asyncio
async def test_copilot_runtime_waits_for_later_tool_results() -> None:
    """Verify that pending tool handlers resume once the northbound client replies."""
    runtime = CopilotRuntime()
    runtime._interactive_sessions['copilot-session-tool'] = (
        _build_interactive_session_state()
    )

    wait_task = asyncio.create_task(
        runtime._wait_for_external_tool_result(
            ToolInvocation(
                session_id='copilot-session-tool',
                tool_call_id='call_readme',
                tool_name='read_file',
                arguments={'path': 'README.md'},
            )
        )
    )
    await asyncio.sleep(0)

    await runtime._submit_interactive_tool_results(
        session_id='copilot-session-tool',
        tool_results=[_build_read_file_tool_result()],
    )
    tool_result = await wait_task

    assert tool_result.text_result_for_llm == 'README contents'
    assert tool_result.result_type == 'success'
    assert (
        runtime._interactive_sessions['copilot-session-tool'].pending_tool_calls == {}
    )


@pytest.mark.asyncio
async def test_copilot_runtime_uses_pre_submitted_tool_results_immediately() -> None:
    """Verify that already-submitted tool results are returned without waiting."""
    runtime = CopilotRuntime()
    runtime._interactive_sessions['copilot-session-tool'] = (
        _build_interactive_session_state()
    )

    await runtime._submit_interactive_tool_results(
        session_id='copilot-session-tool',
        tool_results=[
            _build_read_file_tool_result(
                output_text='cached result',
                is_error=True,
                error_text='tool failed',
            )
        ],
    )
    tool_result = await runtime._wait_for_external_tool_result(
        ToolInvocation(
            session_id='copilot-session-tool',
            tool_call_id='call_readme',
            tool_name='read_file',
            arguments={'path': 'README.md'},
        )
    )

    assert tool_result.text_result_for_llm == 'cached result'
    assert tool_result.result_type == 'failure'
    assert tool_result.error == 'tool failed'
    assert (
        runtime._interactive_sessions['copilot-session-tool'].pending_tool_calls == {}
    )


@pytest.mark.asyncio
async def test_copilot_runtime_continues_after_tool_result_with_follow_up_prompt() -> (
    None
):
    """Verify that continuation requests can trigger a new turn after tool completion."""
    follow_up_events = [
        SessionEvent.from_dict(
            {
                'id': '30000000-0000-0000-0000-000000000021',
                'timestamp': '2025-01-01T00:00:00Z',
                'type': 'assistant.message_delta',
                'data': {'deltaContent': 'INTEGRATION_TOOL_LOOP_OK'},
            }
        ),
        SessionEvent.from_dict(
            {
                'id': '30000000-0000-0000-0000-000000000021',
                'timestamp': '2025-01-01T00:00:00Z',
                'type': 'assistant.message',
                'data': {'content': 'INTEGRATION_TOOL_LOOP_OK'},
            }
        ),
        SessionEvent.from_dict(
            {
                'id': '30000000-0000-0000-0000-000000000022',
                'timestamp': '2025-01-01T00:00:00Z',
                'type': 'assistant.turn_end',
                'data': {'reason': 'stop'},
            }
        ),
    ]
    session = _FakeSession(
        session_id='copilot-session-tool',
        stream_event_batches=[follow_up_events],
    )
    event_queue: asyncio.Queue[SessionEvent] = asyncio.Queue()
    event_queue.put_nowait(
        SessionEvent.from_dict(
            {
                'id': '30000000-0000-0000-0000-000000000020',
                'timestamp': '2025-01-01T00:00:00Z',
                'type': 'assistant.turn_end',
                'data': {'reason': 'stop'},
            }
        )
    )
    session._on_event = event_queue.put_nowait
    runtime = CopilotRuntime()
    interactive_session_state = _build_interactive_session_state(session=session)
    interactive_session_state.event_queue = event_queue
    runtime._interactive_sessions['copilot-session-tool'] = interactive_session_state

    completion = await runtime.complete_chat(
        request=_build_tool_aware_request(
            session_id='copilot-session-tool',
            messages=[CanonicalChatMessage(role='user', content='Continue')],
            tool_results=[_build_read_file_tool_result()],
        ),
        route=ResolvedRoute(runtime='copilot', runtime_model_id='copilot-default'),
    )

    assert completion.output_text == 'INTEGRATION_TOOL_LOOP_OK'
    assert completion.finish_reason == 'stop'
    assert session.sent_prompts == ['Continue.']
    assert session.disconnected is True
    assert runtime._interactive_sessions == {}


@pytest.mark.asyncio
async def test_copilot_runtime_rejects_unknown_interactive_session_ids() -> None:
    """Verify that continuation requests must match a live provider session."""
    runtime = CopilotRuntime()

    with pytest.raises(
        ProviderError, match='No pending provider session matched the supplied'
    ):
        await runtime._get_or_create_interactive_session(
            request=_build_tool_aware_request(session_id='missing-session'),
            route=ResolvedRoute(runtime='copilot', runtime_model_id='copilot-default'),
        )


@pytest.mark.asyncio
async def test_copilot_runtime_rejects_tool_results_without_live_session() -> None:
    """Verify that orphaned tool-result continuations fail fast."""
    session = _FakeSession()
    client = _FakeClient(session=session)
    runtime = CopilotRuntime(client_factory=lambda: cast('CopilotClient', client))

    with pytest.raises(
        ProviderError,
        match=r'Tool-result continuations require a live provider session\.',
    ):
        await runtime.complete_chat(
            request=_build_tool_aware_request(
                messages=[CanonicalChatMessage(role='user', content='Continue')],
                tool_results=[_build_read_file_tool_result()],
            ),
            route=ResolvedRoute(runtime='copilot', runtime_model_id='copilot-default'),
        )

    assert client.create_session_calls == []


def test_copilot_runtime_uses_no_interactive_session_for_noop_policy() -> None:
    """Verify that non-tool requests keep the stateless execution path."""
    runtime = CopilotRuntime()

    assert (
        runtime._uses_interactive_session(
            request=CanonicalChatRequest(
                model_id='gpt-5.4',
                messages=[CanonicalChatMessage(role='user', content='Hello')],
            )
        )
        is False
    )


def test_copilot_runtime_builds_sdk_tool_definitions_for_interactive_requests() -> None:
    """Verify that canonical tool definitions become SDK tool registrations."""
    runtime = CopilotRuntime()

    tool_definitions = [
        CanonicalToolDefinition(
            name='read_file',
            description='Read a file.',
            parameters={
                'type': 'object',
                'properties': {'path': {'type': 'string'}},
            },
        )
    ]
    tools = runtime._build_tool_definitions(
        request=_build_tool_aware_request(tool_definitions=tool_definitions)
    )

    assert len(tools) == 1
    assert tools[0].name == 'read_file'
    assert tools[0].description == 'Read a file.'
    assert tools[0].parameters == {
        'type': 'object',
        'properties': {'path': {'type': 'string'}},
    }
    assert tools[0].overrides_built_in_tool is False
    assert tools[0].skip_permission is True


def test_copilot_runtime_overrides_builtin_apply_patch_tool() -> None:
    """Verify that external apply_patch replaces the SDK built-in tool."""
    runtime = CopilotRuntime()

    tool_definitions = [
        CanonicalToolDefinition(
            name='apply_patch',
            description='Apply a patch.',
        )
    ]
    tools = runtime._build_tool_definitions(
        request=_build_tool_aware_request(tool_definitions=tool_definitions)
    )

    assert len(tools) == 1
    assert tools[0].name == 'apply_patch'
    assert tools[0].overrides_built_in_tool is True
    assert tools[0].skip_permission is True
