"""Unit tests for the Copilot SDK-backed runtime adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import pytest

from copilot_model_provider.core.errors import ProviderError
from copilot_model_provider.core.models import (
    CanonicalChatMessage,
    CanonicalChatRequest,
    ResolvedRoute,
)
from copilot_model_provider.runtimes.copilot import (
    CopilotClientLike,
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


class _FakeSession:
    """Deterministic fake Copilot session for adapter tests."""

    def __init__(
        self,
        *,
        event: _FakeEvent | None = None,
        error: Exception | None = None,
    ) -> None:
        """Store the fake completion behavior for later execution."""
        self._event = event
        self._error = error
        self.prompt: str | None = None
        self.timeout: float | None = None
        self.destroyed = False

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

    def destroy(self) -> None:
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

    def get_state(self) -> str:
        """Return the current fake lifecycle state."""
        return self._state

    def start(self) -> None:
        """Simulate connecting the underlying Copilot client."""
        self.started = True
        self._state = 'connected'

    def create_session(
        self,
        *,
        on_permission_request: PermissionRequestHandler,
        model: str | None = None,
        working_directory: str | None = None,
        streaming: bool | None = None,
    ) -> _FakeSession:
        """Record session creation arguments and return the fake session."""
        self.create_session_calls.append(
            {
                'on_permission_request': on_permission_request,
                'model': model,
                'working_directory': working_directory,
                'streaming': streaming,
            }
        )
        return self._session


def _build_request() -> CanonicalChatRequest:
    """Construct a stable canonical request used by runtime adapter tests."""
    return CanonicalChatRequest(
        model_alias='default',
        messages=[CanonicalChatMessage(role='user', content='Hello')],
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
    assert completion.prompt_tokens == 12
    assert completion.completion_tokens == 5


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
