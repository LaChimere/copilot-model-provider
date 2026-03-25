"""Unit tests for the Copilot SDK-backed runtime adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

import pytest
from copilot.generated.session_events import PermissionRequest, SessionEvent

from copilot_model_provider.core.errors import ProviderError
from copilot_model_provider.core.models import (
    CanonicalChatMessage,
    CanonicalChatRequest,
    ResolvedRoute,
)
from copilot_model_provider.core.policies import PolicyEngine, ToolPermissionPolicy
from copilot_model_provider.runtimes.copilot import (
    CopilotClientLike,
    CopilotRuntimeAdapter,
    PermissionRequestHandler,
)
from copilot_model_provider.tools import (
    MCPRegistry,
    MCPServerDefinition,
    ToolDefinition,
    ToolRegistry,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass
class _FakeEventData:
    """Minimal fake event payload matching the adapter's read path."""

    content: str | None
    message_id: str | None = None
    input_tokens: int | float | str | None = None
    output_tokens: int | float | str | None = None


@dataclass
class _FakeEvent:
    """Minimal fake event wrapper matching the adapter's read path."""

    data: _FakeEventData | None
    type: str = 'assistant.message'


class _FakeSession:
    """Deterministic fake Copilot session for adapter tests."""

    def __init__(
        self,
        *,
        session_id: str = 'copilot-session-1',
        event: _FakeEvent | None = None,
        stream_events: list[Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        """Store the fake completion behavior for later execution."""
        self.session_id = session_id
        self._event = event
        self._stream_events = stream_events or []
        self._error = error
        self.prompt: str | None = None
        self.timeout: float | None = None
        self.destroyed = False
        self.disconnected = False
        self._handlers: list[Any] = []

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
        if self._error is not None:
            raise self._error

        for event in self._stream_events:
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
        """Track that the adapter disconnects sessional sessions."""
        self.disconnected = True

    async def destroy(self) -> None:
        """Track that the adapter always tears the session down."""
        self.destroyed = True


class _FakeClient:
    """Deterministic fake Copilot client for adapter tests."""

    def __init__(self, *, session: _FakeSession, state: str = 'disconnected') -> None:
        """Store the fake session and initial lifecycle state."""
        self._session = session
        self._state = state
        self.started = False
        self.create_session_calls: list[dict[str, Any]] = []
        self.resume_session_calls: list[dict[str, Any]] = []

    def get_state(self) -> str:
        """Return the current fake lifecycle state."""
        return self._state

    def start(self) -> None:
        """Simulate connecting the underlying Copilot client."""
        self.started = True
        self._state = 'connected'

    async def create_session(
        self,
        *,
        on_permission_request: PermissionRequestHandler,
        model: str | None = None,
        session_id: str | None = None,
        working_directory: str | None = None,
        streaming: bool | None = None,
        tools: tuple[object, ...] | None = None,
        mcp_servers: Mapping[str, object] | None = None,
        on_event: Any = None,
    ) -> _FakeSession:
        """Record session creation arguments and return the fake session."""
        self.create_session_calls.append(
            {
                'on_permission_request': on_permission_request,
                'model': model,
                'session_id': session_id,
                'working_directory': working_directory,
                'streaming': streaming,
                'tools': tools,
                'mcp_servers': mcp_servers,
                'on_event': on_event,
            }
        )
        return self._session

    async def resume_session(
        self,
        session_id: str,
        *,
        on_permission_request: PermissionRequestHandler,
        model: str | None = None,
        working_directory: str | None = None,
        streaming: bool | None = None,
        tools: tuple[object, ...] | None = None,
        mcp_servers: Mapping[str, object] | None = None,
        on_event: Any = None,
    ) -> _FakeSession:
        """Record resumed-session arguments and return the fake session."""
        self.resume_session_calls.append(
            {
                'session_id': session_id,
                'on_permission_request': on_permission_request,
                'model': model,
                'working_directory': working_directory,
                'streaming': streaming,
                'tools': tools,
                'mcp_servers': mcp_servers,
                'on_event': on_event,
            }
        )
        return self._session


def _build_request(
    *,
    session_id: str | None = None,
    execution_mode: Literal['stateless', 'sessional'] = 'stateless',
    stream: bool = False,
) -> CanonicalChatRequest:
    """Construct a stable canonical request used by runtime adapter tests."""
    return CanonicalChatRequest(
        session_id=session_id,
        model_alias='default',
        execution_mode=execution_mode,
        messages=[CanonicalChatMessage(role='user', content='Hello')],
        stream=stream,
    )


def _build_permission_request(
    *,
    kind: str = 'custom-tool',
    tool_name: str | None = None,
    server_name: str | None = None,
) -> PermissionRequest:
    """Construct a deterministic permission request for runtime adapter tests."""
    payload: dict[str, object] = {'kind': kind}
    if tool_name is not None:
        payload['toolName'] = tool_name
    if server_name is not None:
        payload['serverName'] = server_name

    return PermissionRequest.from_dict(payload)


@pytest.mark.asyncio
async def test_copilot_runtime_adapter_executes_and_translates_completion() -> None:
    """Verify that the adapter starts the client, sends the prompt, and tears down."""
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
    adapter = CopilotRuntimeAdapter(
        client_factory=lambda: cast('CopilotClientLike', client),
        timeout_seconds=15.0,
        working_directory='/workspace',
    )

    completion = await adapter.complete_chat(
        request=_build_request(),
        route=ResolvedRoute(
            runtime='copilot',
            session_mode='stateless',
            runtime_model_id='copilot-default',
        ),
    )

    assert client.started is True
    assert session.destroyed is True
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


def test_copilot_runtime_adapter_approves_registered_server_tools() -> None:
    """Verify that the runtime approves registered server-approved tool requests."""
    tool_registry = ToolRegistry(
        (
            ToolDefinition(
                name='search-docs',
                description='Search provider documentation.',
                input_schema={'type': 'object'},
            ),
        )
    )
    adapter = CopilotRuntimeAdapter(tool_registry=tool_registry)

    result = adapter._handle_permission_request(
        _build_permission_request(tool_name='search-docs'),
        {},
    )

    assert result.kind == 'approved'
    assert result.message is not None
    assert 'server-approved' in result.message


def test_copilot_runtime_adapter_denies_unknown_tools() -> None:
    """Verify that unknown custom tools remain denied by the runtime policy."""
    adapter = CopilotRuntimeAdapter()

    result = adapter._handle_permission_request(
        _build_permission_request(tool_name='unknown-tool'),
        {},
    )

    assert result.kind == 'denied-by-rules'
    assert result.message is not None
    assert 'not registered' in result.message


def test_copilot_runtime_adapter_shares_default_mcp_registry_with_policy_engine() -> (
    None
):
    """Verify that default MCP registration is visible to later policy checks."""
    adapter = CopilotRuntimeAdapter()
    adapter._mcp_registry.register(
        MCPServerDefinition(
            name='docs-api',
            transport='http',
            url='http://localhost:8123/mcp',
        )
    )

    result = adapter._handle_permission_request(
        _build_permission_request(kind='mcp', server_name='docs-api'),
        {},
    )

    assert result.kind == 'approved'


def test_copilot_runtime_adapter_honors_builtin_tool_allow_list() -> None:
    """Verify that built-in SDK tool requests follow the configured built-in policy."""
    adapter = CopilotRuntimeAdapter(
        policy_engine=PolicyEngine(
            tool_policy=ToolPermissionPolicy(
                builtin_tool_policy='allow-listed',
                allowed_builtin_tool_names=frozenset({'view'}),
            )
        )
    )

    allowed = adapter._handle_permission_request(
        _build_permission_request(kind='read', tool_name='view'),
        {},
    )
    denied = adapter._handle_permission_request(
        _build_permission_request(kind='shell', tool_name='bash'),
        {},
    )

    assert allowed.kind == 'approved'
    assert denied.kind == 'denied-by-rules'


def test_copilot_runtime_adapter_approves_registered_mcp_servers() -> None:
    """Verify that MCP permission requests are approved for registered servers."""
    mcp_registry = MCPRegistry(
        (
            MCPServerDefinition(
                name='docs-api',
                transport='http',
                url='http://localhost:8123/mcp',
            ),
        )
    )
    adapter = CopilotRuntimeAdapter(
        mcp_registry=mcp_registry,
        policy_engine=PolicyEngine(mcp_registry=mcp_registry),
    )

    result = adapter._handle_permission_request(
        _build_permission_request(kind='mcp', server_name='docs-api'),
        {},
    )

    assert result.kind == 'approved'


@pytest.mark.asyncio
async def test_copilot_runtime_adapter_passes_registered_mcp_servers_to_sdk() -> None:
    """Verify that configured MCP mounts are forwarded into SDK session creation."""
    session = _FakeSession(
        event=_FakeEvent(
            data=_FakeEventData(
                content='Hi from Copilot',
                message_id='chatcmpl-fake',
            )
        )
    )
    client = _FakeClient(session=session)
    adapter = CopilotRuntimeAdapter(
        client_factory=lambda: cast('CopilotClientLike', client),
        mcp_registry=MCPRegistry(
            (
                MCPServerDefinition(
                    name='docs-api',
                    transport='http',
                    url='http://localhost:8123/mcp',
                    tools=('search_docs',),
                ),
            )
        ),
    )

    await adapter.complete_chat(
        request=_build_request(),
        route=ResolvedRoute(
            runtime='copilot',
            session_mode='stateless',
            runtime_model_id='copilot-default',
        ),
    )

    assert client.create_session_calls[0]['mcp_servers'] == {
        'docs-api': {
            'type': 'http',
            'url': 'http://localhost:8123/mcp',
            'tools': ['search_docs'],
        }
    }


@pytest.mark.asyncio
async def test_copilot_runtime_adapter_passes_registered_tools_to_sdk() -> None:
    """Verify that registered executable tools are forwarded into SDK sessions."""

    def _handler(invocation: Any) -> Any:
        """Return a deterministic payload for the fake runtime test."""
        return {'query': invocation.arguments}

    session = _FakeSession(
        event=_FakeEvent(
            data=_FakeEventData(
                content='Hi from Copilot',
                message_id='chatcmpl-fake',
            )
        )
    )
    client = _FakeClient(session=session)
    tool_registry = ToolRegistry(
        (
            ToolDefinition(
                name='search-docs',
                description='Search provider documentation.',
                input_schema={'type': 'object'},
                handler=_handler,
            ),
        )
    )
    adapter = CopilotRuntimeAdapter(
        client_factory=lambda: cast('CopilotClientLike', client),
        tool_registry=tool_registry,
        policy_engine=PolicyEngine(tool_registry=tool_registry),
    )

    await adapter.complete_chat(
        request=_build_request(),
        route=ResolvedRoute(
            runtime='copilot',
            session_mode='stateless',
            runtime_model_id='copilot-default',
        ),
    )

    tools = client.create_session_calls[0]['tools']
    assert tools is not None
    assert len(tools) == 1
    assert tools[0].name == 'search-docs'


@pytest.mark.asyncio
async def test_copilot_runtime_adapter_raises_when_runtime_returns_no_content() -> None:
    """Verify that empty assistant messages become structured provider failures."""
    session = _FakeSession(event=_FakeEvent(data=_FakeEventData(content=None)))
    adapter = CopilotRuntimeAdapter(
        client_factory=lambda: cast('CopilotClientLike', _FakeClient(session=session))
    )

    with pytest.raises(ProviderError, match='Copilot runtime returned no assistant'):
        await adapter.complete_chat(
            request=_build_request(),
            route=ResolvedRoute(
                runtime='copilot',
                session_mode='stateless',
                runtime_model_id='copilot-default',
            ),
        )


@pytest.mark.asyncio
async def test_copilot_runtime_adapter_raises_when_runtime_returns_no_event_data() -> (
    None
):
    """Verify that missing event data becomes a structured provider failure."""
    session = _FakeSession(event=_FakeEvent(data=None))
    adapter = CopilotRuntimeAdapter(
        client_factory=lambda: cast('CopilotClientLike', _FakeClient(session=session))
    )

    with pytest.raises(ProviderError, match='Copilot runtime returned no assistant'):
        await adapter.complete_chat(
            request=_build_request(),
            route=ResolvedRoute(
                runtime='copilot',
                session_mode='stateless',
                runtime_model_id='copilot-default',
            ),
        )


@pytest.mark.asyncio
async def test_copilot_runtime_adapter_raises_when_token_metadata_is_invalid() -> None:
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
    adapter = CopilotRuntimeAdapter(
        client_factory=lambda: cast('CopilotClientLike', _FakeClient(session=session))
    )

    with pytest.raises(ProviderError, match='invalid token metadata'):
        await adapter.complete_chat(
            request=_build_request(),
            route=ResolvedRoute(
                runtime='copilot',
                session_mode='stateless',
                runtime_model_id='copilot-default',
            ),
        )


@pytest.mark.asyncio
async def test_copilot_runtime_adapter_resumes_and_disconnects_sessional_requests() -> (
    None
):
    """Verify that sessional requests resume existing sessions without destroying them."""
    session = _FakeSession(
        session_id='copilot-session-resume',
        event=_FakeEvent(data=_FakeEventData(content='Resumed response')),
    )
    client = _FakeClient(session=session)
    adapter = CopilotRuntimeAdapter(
        client_factory=lambda: cast('CopilotClientLike', client)
    )

    completion = await adapter.complete_chat(
        request=_build_request(
            session_id='copilot-session-resume',
            execution_mode='sessional',
        ),
        route=ResolvedRoute(
            runtime='copilot',
            session_mode='sessional',
            runtime_model_id='copilot-default',
        ),
    )

    assert client.resume_session_calls[0]['session_id'] == 'copilot-session-resume'
    assert session.disconnected is True
    assert session.destroyed is False
    assert completion.session_id == 'copilot-session-resume'


@pytest.mark.asyncio
async def test_copilot_runtime_adapter_streams_events_and_keeps_session_id() -> None:
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
    adapter = CopilotRuntimeAdapter(
        client_factory=lambda: cast('CopilotClientLike', client)
    )

    runtime_stream = await adapter.stream_chat(
        request=_build_request(stream=True),
        route=ResolvedRoute(
            runtime='copilot',
            session_mode='stateless',
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
    assert session.destroyed is True
    assert session.disconnected is False
