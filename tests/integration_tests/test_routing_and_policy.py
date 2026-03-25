"""Release-gate integration tests for routing and alias policy behavior."""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass
class _CapturedCall:
    """Captured route metadata for one fake runtime execution."""

    runtime_model_id: str | None
    execution_mode: str
    session_id: str | None


class _RoutingAwareRuntimeAdapter(RuntimeAdapter):
    """Fake runtime that exposes resolved routing metadata through HTTP tests."""

    def __init__(self) -> None:
        """Initialize deterministic capture state for routing tests."""
        super().__init__(runtime_name='copilot')
        self.calls: list[_CapturedCall] = []
        self._created_sessions = 0

    @override
    def default_route(self) -> ResolvedRoute:
        """Return the runtime's default stateless route."""
        return ResolvedRoute(runtime='copilot', session_mode='stateless')

    @override
    async def check_health(self) -> RuntimeHealth:
        """Return a healthy fake runtime payload."""
        return RuntimeHealth(runtime='copilot', available=True, detail='ok')

    @override
    async def complete_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeCompletion:
        """Capture route metadata and echo it back through the response body."""
        self.calls.append(
            _CapturedCall(
                runtime_model_id=route.runtime_model_id,
                execution_mode=request.execution_mode,
                session_id=request.session_id,
            )
        )
        if request.session_id is None and request.execution_mode == 'sessional':
            self._created_sessions += 1
            session_id = f'copilot-session-{self._created_sessions}'
        else:
            session_id = request.session_id

        return RuntimeCompletion(
            output_text=(
                f'{route.runtime_model_id}:{request.execution_mode}:{session_id or "new"}'
            ),
            session_id=session_id,
        )

    @override
    async def stream_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeEventStream:
        """Fail fast because Step 5 routing tests only exercise non-streaming HTTP."""
        del request, route
        msg = 'Streaming is not used by the routing/policy release-gate tests.'
        raise AssertionError(msg)


def _build_release_gate_catalog() -> ModelCatalog:
    """Build a catalog with distinct aliases for routing and session-mode checks."""
    return ModelCatalog(
        entries=(
            ModelCatalogEntry(
                alias='default',
                runtime='copilot',
                owned_by='test-suite',
                runtime_model_id='copilot-default',
                created=111,
            ),
            ModelCatalogEntry(
                alias='fast',
                runtime='copilot',
                owned_by='test-suite',
                runtime_model_id='copilot-fast',
                created=222,
            ),
            ModelCatalogEntry(
                alias='persistent',
                runtime='copilot',
                owned_by='test-suite',
                runtime_model_id='copilot-persistent',
                created=333,
                session_mode='sessional',
            ),
        )
    )


@pytest.mark.asyncio
async def test_release_gate_models_and_chat_routes_respect_alias_routing() -> None:
    """Verify that model listing and chat execution honor alias-specific routing."""
    runtime_adapter = _RoutingAwareRuntimeAdapter()
    async with build_async_client(
        runtime_adapter=runtime_adapter,
        model_catalog=_build_release_gate_catalog(),
    ) as client:
        models_response = await client.get('/v1/models')
        default_response = await client.post(
            '/v1/chat/completions',
            json={
                'model': 'default',
                'messages': [{'role': 'user', 'content': 'Ping'}],
            },
        )
        fast_response = await client.post(
            '/v1/chat/completions',
            json={
                'model': 'fast',
                'messages': [{'role': 'user', 'content': 'Ping'}],
            },
        )

    assert models_response.status_code == 200
    models_payload = models_response.json()
    assert [item['id'] for item in models_payload['data']] == [
        'default',
        'fast',
        'persistent',
    ]
    assert [item['created'] for item in models_payload['data']] == [111, 222, 333]
    assert [item['owned_by'] for item in models_payload['data']] == [
        'test-suite',
        'test-suite',
        'test-suite',
    ]

    assert default_response.status_code == 200
    assert fast_response.status_code == 200
    assert default_response.json()['choices'][0]['message']['content'] == (
        'copilot-default:stateless:new'
    )
    assert fast_response.json()['choices'][0]['message']['content'] == (
        'copilot-fast:stateless:new'
    )
    assert runtime_adapter.calls[:2] == [
        _CapturedCall(
            runtime_model_id='copilot-default',
            execution_mode='stateless',
            session_id=None,
        ),
        _CapturedCall(
            runtime_model_id='copilot-fast',
            execution_mode='stateless',
            session_id=None,
        ),
    ]


@pytest.mark.asyncio
async def test_release_gate_sessional_alias_requires_header_and_persists_route_state() -> (
    None
):
    """Verify that sessional aliases enforce headers and persist the routed model."""
    runtime_adapter = _RoutingAwareRuntimeAdapter()
    model_catalog = _build_release_gate_catalog()
    with managed_scratch_directory('integration-routing-policy') as scratch:
        session_map = FileBackedSessionMap(scratch / 'session-map')
        session_lock_manager = FileBackedSessionLockManager(scratch / 'locks')
        async with build_async_client(
            runtime_adapter=runtime_adapter,
            model_catalog=model_catalog,
            session_map=session_map,
            session_lock_manager=session_lock_manager,
        ) as client:
            missing_header_response = await client.post(
                '/v1/chat/completions',
                json={
                    'model': 'persistent',
                    'messages': [{'role': 'user', 'content': 'Ping'}],
                },
            )
            successful_response = await client.post(
                '/v1/chat/completions',
                headers={'X-Copilot-Conversation-Id': 'conversation-1'},
                json={
                    'model': 'persistent',
                    'messages': [{'role': 'user', 'content': 'Ping'}],
                },
            )

        stored_entry = session_map.get('conversation-1')

    assert missing_header_response.status_code == 400
    assert missing_header_response.json() == {
        'error': {
            'code': 'conversation_id_required',
            'message': (
                'Sessional chat requests require the X-Copilot-Conversation-Id header.'
            ),
        }
    }
    assert successful_response.status_code == 200
    assert successful_response.json()['choices'][0]['message']['content'] == (
        'copilot-persistent:sessional:copilot-session-1'
    )
    assert runtime_adapter.calls == [
        _CapturedCall(
            runtime_model_id='copilot-persistent',
            execution_mode='sessional',
            session_id=None,
        )
    ]
    assert stored_entry is not None
    assert stored_entry.runtime_model_id == 'copilot-persistent'
    assert stored_entry.copilot_session_id == 'copilot-session-1'


@pytest.mark.asyncio
async def test_release_gate_unknown_alias_fails_with_clean_404() -> None:
    """Verify that unknown aliases fail with the shared structured error envelope."""
    async with build_async_client(
        runtime_adapter=_RoutingAwareRuntimeAdapter(),
        model_catalog=_build_release_gate_catalog(),
    ) as client:
        response = await client.post(
            '/v1/chat/completions',
            json={
                'model': 'missing-model',
                'messages': [{'role': 'user', 'content': 'Ping'}],
            },
        )

    assert response.status_code == 404
    assert response.json() == {
        'error': {
            'code': 'model_not_found',
            'message': "Unknown model alias: 'missing-model'",
        }
    }
