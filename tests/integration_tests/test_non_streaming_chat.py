"""Lightweight integration smoke tests for the non-streaming chat route."""

from __future__ import annotations

from typing import override

import pytest

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


class _SmokeRuntimeAdapter(RuntimeAdapter):
    """Small fake runtime that lets the in-process app execute chat requests."""

    def __init__(self) -> None:
        """Initialize the smoke adapter with the repository's Copilot runtime name."""
        super().__init__(runtime_name='copilot')

    @override
    def default_route(self) -> ResolvedRoute:
        """Return a default stateless route for smoke-test execution."""
        return ResolvedRoute(runtime='copilot', session_mode='stateless')

    @override
    async def check_health(self) -> RuntimeHealth:
        """Report a healthy runtime payload for smoke tests."""
        return RuntimeHealth(runtime='copilot', available=True, detail='ok')

    @override
    async def complete_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeCompletion:
        """Echo deterministic response text so the wire path is easy to verify."""
        del request, route
        return RuntimeCompletion(output_text='Smoke test reply.')

    @override
    async def stream_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeEventStream:
        """Fail fast if a non-streaming smoke test accidentally calls streaming."""
        del request, route
        msg = 'Streaming is not used by the non-streaming smoke tests.'
        raise AssertionError(msg)


class _SessionAwareRuntimeAdapter(RuntimeAdapter):
    """Fake runtime that exposes stable session IDs for convergence tests."""

    def __init__(self) -> None:
        """Initialize deterministic session tracking for session-backed tests."""
        super().__init__(runtime_name='copilot')
        self.session_ids_seen: list[str | None] = []
        self.auth_subjects_seen: list[str | None] = []
        self._created_sessions = 0

    @override
    def default_route(self) -> ResolvedRoute:
        """Return a session-backed route for convergence testing."""
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
        """Return a deterministic response and stable session ID for follow-ups."""
        del route
        self.session_ids_seen.append(request.session_id)
        self.auth_subjects_seen.append(request.auth_subject)
        if request.session_id is None:
            self._created_sessions += 1
            session_id = f'copilot-session-{self._created_sessions}'
        else:
            session_id = request.session_id

        return RuntimeCompletion(
            output_text=f'Session reply #{self._created_sessions or 1}.',
            session_id=session_id,
        )

    @override
    async def stream_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeEventStream:
        """Fail fast if the non-streaming convergence test hits streaming."""
        del request, route
        msg = 'Streaming is not used by this non-streaming convergence test.'
        raise AssertionError(msg)


@pytest.mark.asyncio
async def test_non_streaming_chat_smoke_path_executes_over_http() -> None:
    """Verify that the in-process app boots and serves chat completions over HTTP."""
    async with build_async_client(runtime_adapter=_SmokeRuntimeAdapter()) as client:
        response = await client.post(
            '/v1/chat/completions',
            json={
                'model': 'default',
                'messages': [{'role': 'user', 'content': 'Ping'}],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload['object'] == 'chat.completion'
    assert payload['choices'][0]['message']['content'] == 'Smoke test reply.'


@pytest.mark.asyncio
async def test_non_streaming_chat_sessional_path_persists_and_resumes_session_ids() -> (
    None
):
    """Verify that session-backed HTTP requests persist and resume Copilot sessions."""
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
    runtime_adapter = _SessionAwareRuntimeAdapter()
    with managed_scratch_directory('integration-convergence-non-streaming') as scratch:
        session_map = FileBackedSessionMap(scratch / 'session-map')
        session_lock_manager = FileBackedSessionLockManager(scratch / 'locks')
        async with build_async_client(
            runtime_adapter=runtime_adapter,
            model_catalog=model_catalog,
            session_map=session_map,
            session_lock_manager=session_lock_manager,
        ) as client:
            for prompt in ('Ping', 'Follow up'):
                response = await client.post(
                    '/v1/chat/completions',
                    headers={'X-Copilot-Conversation-Id': 'conversation-1'},
                    json={
                        'model': 'default',
                        'messages': [{'role': 'user', 'content': prompt}],
                    },
                )
                assert response.status_code == 200

        stored_entry = session_map.get('conversation-1')

    assert runtime_adapter.session_ids_seen == [None, 'copilot-session-1']
    assert stored_entry is not None
    assert stored_entry.copilot_session_id == 'copilot-session-1'


@pytest.mark.asyncio
async def test_non_streaming_chat_sessional_path_binds_resume_to_same_auth_subject() -> (
    None
):
    """Verify that resumed sessional turns stay bound to the original auth subject."""
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
    runtime_adapter = _SessionAwareRuntimeAdapter()
    with managed_scratch_directory('integration-convergence-auth-binding') as scratch:
        session_map = FileBackedSessionMap(scratch / 'session-map')
        session_lock_manager = FileBackedSessionLockManager(scratch / 'locks')
        async with build_async_client(
            runtime_adapter=runtime_adapter,
            model_catalog=model_catalog,
            session_map=session_map,
            session_lock_manager=session_lock_manager,
        ) as client:
            first_response = await client.post(
                '/v1/chat/completions',
                headers={
                    'X-Copilot-Conversation-Id': 'conversation-auth',
                    'Authorization': 'Bearer github-token-1',
                },
                json={
                    'model': 'default',
                    'messages': [{'role': 'user', 'content': 'Ping'}],
                },
            )
            second_response = await client.post(
                '/v1/chat/completions',
                headers={
                    'X-Copilot-Conversation-Id': 'conversation-auth',
                    'Authorization': 'Bearer github-token-2',
                },
                json={
                    'model': 'default',
                    'messages': [{'role': 'user', 'content': 'Follow up'}],
                },
            )

        stored_entry = session_map.get('conversation-auth')

    assert first_response.status_code == 200
    assert second_response.status_code == 403
    assert second_response.json()['error']['code'] == 'session_auth_subject_mismatch'
    assert runtime_adapter.session_ids_seen == [None]
    assert runtime_adapter.auth_subjects_seen == [
        stored_entry.auth_subject if stored_entry else None
    ]
    assert stored_entry is not None
    assert stored_entry.auth_subject is not None
    assert 'github-token-1' not in stored_entry.auth_subject
