"""Integration tests for Step 3 streaming/session convergence over HTTP."""

from __future__ import annotations

from typing import TYPE_CHECKING, override

import pytest
from copilot.generated.session_events import SessionEvent

from copilot_model_provider.core.catalog import ModelCatalog
from copilot_model_provider.core.models import (
    CanonicalChatRequest,
    ModelCatalogEntry,
    ResolvedRoute,
    RuntimeCompletion,
    RuntimeHealth,
)
from copilot_model_provider.runtimes.base import RuntimeAdapter, RuntimeEventStream
from copilot_model_provider.storage import (
    FileBackedSessionLockManager,
    FileBackedSessionMap,
    SessionMapEntry,
)
from tests.integration_tests.harness import build_async_client
from tests.session_persistence_helpers import managed_scratch_directory

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class _StreamingRuntimeAdapter(RuntimeAdapter):
    """Deterministic runtime adapter for streaming convergence tests."""

    def __init__(self) -> None:
        """Initialize deterministic stream/session tracking."""
        super().__init__(runtime_name='copilot')
        self.session_ids_seen: list[str | None] = []
        self._created_sessions = 0

    @override
    def default_route(self) -> ResolvedRoute:
        """Return a session-backed default route for convergence tests."""
        return ResolvedRoute(runtime='copilot', session_mode='sessional')

    @override
    async def check_health(self) -> RuntimeHealth:
        """Return a healthy runtime payload for convergence tests."""
        return RuntimeHealth(runtime='copilot', available=True, detail='ok')

    @override
    async def complete_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeCompletion:
        """Fail fast if a streaming convergence test accidentally calls complete_chat."""
        del request, route
        msg = 'Non-streaming execution is not used by the streaming convergence test.'
        raise AssertionError(msg)

    @override
    async def stream_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeEventStream:
        """Return a deterministic stream and stable session ID for follow-up turns."""
        del route
        self.session_ids_seen.append(request.session_id)
        if request.session_id is None:
            self._created_sessions += 1
            session_id = f'copilot-session-stream-{self._created_sessions}'
        else:
            session_id = request.session_id

        async def _events() -> AsyncIterator[SessionEvent]:
            """Yield a minimal assistant turn as SDK events."""
            for event in (
                SessionEvent.from_dict(
                    {
                        'id': '00000000-0000-0000-0000-000000000011',
                        'timestamp': '2025-01-01T00:00:00Z',
                        'type': 'assistant.message_delta',
                        'data': {'deltaContent': 'Hello'},
                    }
                ),
                SessionEvent.from_dict(
                    {
                        'id': '00000000-0000-0000-0000-000000000012',
                        'timestamp': '2025-01-01T00:00:00Z',
                        'type': 'assistant.turn_end',
                        'data': {'reason': 'stop'},
                    }
                ),
            ):
                yield event

        return RuntimeEventStream(session_id=session_id, events=_events())


class _CloseTrackingStreamingRuntimeAdapter(_StreamingRuntimeAdapter):
    """Streaming runtime that exposes whether pre-stream cleanup was invoked."""

    def __init__(self) -> None:
        """Initialize deterministic cleanup tracking for failure tests."""
        super().__init__()
        self.close_called = False

    @override
    async def stream_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeEventStream:
        """Wrap the base runtime stream with an explicit close callback."""
        runtime_stream = await super().stream_chat(request=request, route=route)

        async def _close() -> None:
            """Record cleanup when the HTTP layer aborts before streaming starts."""
            self.close_called = True

        return RuntimeEventStream(
            session_id=runtime_stream.session_id,
            events=runtime_stream.events,
            close=_close,
        )


class _FailingSessionMap(FileBackedSessionMap):
    """Session map that raises during persistence to simulate setup failures."""

    @override
    def put(self, entry: SessionMapEntry) -> SessionMapEntry:
        """Raise a deterministic error while preserving the method contract shape."""
        del entry
        msg = 'persist failed before streaming response start'
        raise RuntimeError(msg)


@pytest.mark.asyncio
async def test_streaming_chat_sessional_path_streams_and_resumes_session_ids() -> None:
    """Verify that streaming HTTP requests emit SSE and reuse persisted sessions."""
    model_catalog = ModelCatalog(
        entries=(
            ModelCatalogEntry(
                alias='default',
                runtime='copilot',
                owned_by='test',
                runtime_model_id='copilot-default',
                session_mode='sessional',
            ),
        )
    )
    runtime_adapter = _StreamingRuntimeAdapter()
    with managed_scratch_directory('integration-convergence-streaming') as scratch:
        session_map = FileBackedSessionMap(scratch / 'session-map')
        session_lock_manager = FileBackedSessionLockManager(scratch / 'locks')
        async with build_async_client(
            runtime_adapter=runtime_adapter,
            model_catalog=model_catalog,
            session_map=session_map,
            session_lock_manager=session_lock_manager,
        ) as client:
            payloads: list[str] = []
            for prompt in ('Ping', 'Follow up'):
                async with client.stream(
                    'POST',
                    '/v1/chat/completions',
                    headers={'X-Copilot-Conversation-Id': 'conversation-stream'},
                    json={
                        'model': 'default',
                        'stream': True,
                        'messages': [{'role': 'user', 'content': prompt}],
                    },
                ) as response:
                    assert response.status_code == 200
                    assert response.headers['content-type'].startswith(
                        'text/event-stream'
                    )
                    payloads.append(
                        ''.join([chunk async for chunk in response.aiter_text()])
                    )

        stored_entry = session_map.get('conversation-stream')

    assert runtime_adapter.session_ids_seen == [None, 'copilot-session-stream-1']
    assert stored_entry is not None
    assert stored_entry.copilot_session_id == 'copilot-session-stream-1'
    assert all('"object":"chat.completion.chunk"' in payload for payload in payloads)
    assert all('"content":"Hello"' in payload for payload in payloads)
    assert all('data: [DONE]\n\n' in payload for payload in payloads)


@pytest.mark.asyncio
async def test_streaming_chat_releases_lock_and_runtime_when_persist_fails() -> None:
    """Verify cleanup runs when streaming setup fails before the response starts."""
    model_catalog = ModelCatalog(
        entries=(
            ModelCatalogEntry(
                alias='default',
                runtime='copilot',
                owned_by='test',
                runtime_model_id='copilot-default',
                session_mode='sessional',
            ),
        )
    )
    runtime_adapter = _CloseTrackingStreamingRuntimeAdapter()
    with managed_scratch_directory(
        'integration-convergence-streaming-failure'
    ) as scratch:
        session_map = _FailingSessionMap(scratch / 'session-map')
        session_lock_manager = FileBackedSessionLockManager(scratch / 'locks')
        async with build_async_client(
            runtime_adapter=runtime_adapter,
            model_catalog=model_catalog,
            session_map=session_map,
            session_lock_manager=session_lock_manager,
        ) as client:
            with pytest.raises(RuntimeError, match='persist failed before streaming'):
                await client.post(
                    '/v1/chat/completions',
                    headers={'X-Copilot-Conversation-Id': 'conversation-stream'},
                    json={
                        'model': 'default',
                        'stream': True,
                        'messages': [{'role': 'user', 'content': 'Ping'}],
                    },
                )

        held_lock = session_lock_manager.inspect('conversation-stream')

    assert runtime_adapter.close_called is True
    assert held_lock is None
