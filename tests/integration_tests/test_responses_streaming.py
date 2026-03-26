"""Integration tests for Responses session/header convergence over HTTP."""

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
)
from tests.integration_tests.harness import build_async_client
from tests.session_persistence_helpers import managed_scratch_directory

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class _StreamingResponsesRuntimeAdapter(RuntimeAdapter):
    """Deterministic runtime adapter for Responses streaming convergence tests."""

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
        msg = 'Non-streaming execution is not used by the Responses streaming test.'
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
            session_id = f'copilot-session-responses-{self._created_sessions}'
        else:
            session_id = request.session_id

        async def _events() -> AsyncIterator[SessionEvent]:
            """Yield a minimal assistant turn as SDK events."""
            for event in (
                SessionEvent.from_dict(
                    {
                        'id': '00000000-0000-0000-0000-000000000201',
                        'timestamp': '2025-01-01T00:00:00Z',
                        'type': 'assistant.message_delta',
                        'data': {'deltaContent': 'Hello'},
                    }
                ),
                SessionEvent.from_dict(
                    {
                        'id': '00000000-0000-0000-0000-000000000202',
                        'timestamp': '2025-01-01T00:00:00Z',
                        'type': 'assistant.turn_end',
                        'data': {'reason': 'stop'},
                    }
                ),
            ):
                yield event

        return RuntimeEventStream(session_id=session_id, events=_events())


@pytest.mark.asyncio
async def test_streaming_responses_sessional_path_uses_session_id_header_for_resume() -> (
    None
):
    """Verify that ``session_id`` drives internal session persistence for Responses."""
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
    runtime_adapter = _StreamingResponsesRuntimeAdapter()
    with managed_scratch_directory('integration-responses-streaming') as scratch:
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
                    '/v1/responses',
                    headers={'session_id': 'codex-session-stream'},
                    json={
                        'model': 'default',
                        'stream': True,
                        'input': prompt,
                    },
                ) as response:
                    assert response.status_code == 200
                    assert response.headers['content-type'].startswith(
                        'text/event-stream'
                    )
                    payloads.append(
                        ''.join([chunk async for chunk in response.aiter_text()])
                    )

        stored_entry = session_map.get('codex-session-stream')

    assert runtime_adapter.session_ids_seen == [None, 'copilot-session-responses-1']
    assert stored_entry is not None
    assert stored_entry.copilot_session_id == 'copilot-session-responses-1'
    assert all('"type":"response.created"' in payload for payload in payloads)
    assert all('"type":"response.completed"' in payload for payload in payloads)
