"""Unit tests for the Copilot SDK-backed runtime adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import pytest
from copilot import CopilotClient, SubprocessConfig
from copilot.generated.session_events import PermissionRequest, SessionEvent

from copilot_model_provider.core.errors import ProviderError
from copilot_model_provider.core.models import (
    CanonicalChatMessage,
    CanonicalChatRequest,
    ResolvedRoute,
)
from copilot_model_provider.runtimes.copilot import (
    CopilotRuntimeAdapter,
    PermissionRequestHandler,
)


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
        """Track that the adapter tears the session down after each request."""
        self.disconnected = True


class _FakeClient:
    """Deterministic fake Copilot client for adapter tests."""

    def __init__(self, *, session: _FakeSession, state: str = 'disconnected') -> None:
        """Store the fake session and initial lifecycle state."""
        self._session = session
        self._state = state
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
        working_directory: str | None = None,
        streaming: bool | None = None,
        on_event: Any = None,
    ) -> _FakeSession:
        """Record session creation arguments and return the fake session."""
        self.create_session_calls.append(
            {
                'on_permission_request': on_permission_request,
                'model': model,
                'working_directory': working_directory,
                'streaming': streaming,
                'on_event': on_event,
            }
        )
        return self._session


def _build_request(
    *,
    runtime_auth_token: str | None = None,
    stream: bool = False,
) -> CanonicalChatRequest:
    """Construct a stable canonical request used by runtime adapter tests."""
    return CanonicalChatRequest(
        runtime_auth_token=runtime_auth_token,
        model_alias='default',
        messages=[CanonicalChatMessage(role='user', content='Hello')],
        stream=stream,
    )


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
        client_factory=lambda: cast('CopilotClient', client),
        timeout_seconds=15.0,
        working_directory='/workspace',
    )

    completion = await adapter.complete_chat(
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


def test_copilot_runtime_adapter_defaults_to_subprocess_mode() -> None:
    """Verify that the adapter reports subprocess mode."""
    adapter = CopilotRuntimeAdapter()

    assert adapter.connection_mode == 'subprocess'


def test_copilot_runtime_adapter_builds_default_client_without_external_config(
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
        'copilot_model_provider.runtimes.copilot.CopilotClient',
        _CapturedClient,
    )

    adapter = CopilotRuntimeAdapter()
    adapter._get_or_create_client()

    assert captured_arguments['config'] is None
    assert captured_arguments['auto_start'] is False


def test_copilot_runtime_adapter_builds_authenticated_subprocess_client(
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
        'copilot_model_provider.runtimes.copilot.CopilotClient',
        _CapturedClient,
    )

    adapter = CopilotRuntimeAdapter(working_directory='/workspace')
    adapter._build_authenticated_client('github-token-123')

    config = cast('SubprocessConfig', captured_arguments['config'])
    assert isinstance(config, SubprocessConfig)
    assert config.github_token == 'github-token-123'  # noqa: S105 - deterministic test token
    assert config.cwd == '/workspace'
    assert captured_arguments['auto_start'] is False


@pytest.mark.asyncio
async def test_copilot_runtime_adapter_uses_authenticated_client_factory_for_bearer_tokens() -> (
    None
):
    """Verify that bearer-token requests use a short-lived authenticated client."""
    default_client = _FakeClient(session=_FakeSession())
    authed_session = _FakeSession(
        event=_FakeEvent(data=_FakeEventData(content='Hi from authed client'))
    )
    authed_client = _FakeClient(session=authed_session)
    captured_tokens: list[str] = []
    adapter = CopilotRuntimeAdapter(
        client_factory=lambda: cast('CopilotClient', default_client),
        authenticated_client_factory=lambda token: (
            captured_tokens.append(token) or cast('CopilotClient', authed_client)
        ),
    )

    completion = await adapter.complete_chat(
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


def test_copilot_runtime_adapter_denies_runtime_permission_requests() -> None:
    """Verify that the thin provider denies server-side permission requests."""
    adapter = CopilotRuntimeAdapter()
    result = adapter._deny_permission_request(
        PermissionRequest.from_dict({'kind': 'custom-tool', 'toolName': 'bash'}),
        {},
    )

    assert result.kind == 'denied-by-rules'
    assert 'disabled' in cast('str', result.message)


@pytest.mark.asyncio
async def test_copilot_runtime_adapter_raises_when_runtime_returns_no_content() -> None:
    """Verify that empty assistant messages become structured provider failures."""
    session = _FakeSession(event=_FakeEvent(data=_FakeEventData(content=None)))
    adapter = CopilotRuntimeAdapter(
        client_factory=lambda: cast('CopilotClient', _FakeClient(session=session))
    )

    with pytest.raises(ProviderError, match='Copilot runtime returned no assistant'):
        await adapter.complete_chat(
            request=_build_request(),
            route=ResolvedRoute(
                runtime='copilot',
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
        client_factory=lambda: cast('CopilotClient', _FakeClient(session=session))
    )

    with pytest.raises(ProviderError, match='Copilot runtime returned no assistant'):
        await adapter.complete_chat(
            request=_build_request(),
            route=ResolvedRoute(
                runtime='copilot',
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
        client_factory=lambda: cast('CopilotClient', _FakeClient(session=session))
    )

    with pytest.raises(ProviderError, match='invalid token metadata'):
        await adapter.complete_chat(
            request=_build_request(),
            route=ResolvedRoute(
                runtime='copilot',
                runtime_model_id='copilot-default',
            ),
        )


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
        client_factory=lambda: cast('CopilotClient', client)
    )

    runtime_stream = await adapter.stream_chat(
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
