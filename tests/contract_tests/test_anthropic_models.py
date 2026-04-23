"""Contract tests for the Anthropic-compatible model catalog endpoint."""

from __future__ import annotations

from typing import override

import pytest

from copilot_model_provider.core.models import (
    CopilotModelCapabilities,
    CopilotModelLimits,
    CopilotModelMetadata,
    ResolvedRoute,
    RuntimeCompletion,
    RuntimeDiscoveredModel,
    RuntimeHealth,
)
from copilot_model_provider.runtimes.protocols import (
    RuntimeEventStream,
    RuntimeProtocol,
)
from tests.harness import build_async_client


class _FakeAnthropicModelsRuntime(RuntimeProtocol):
    """Deterministic runtime used by the Anthropic models contract test."""

    @property
    @override
    def runtime_name(self) -> str:
        """Return the stable runtime identifier used by the fake runtime."""
        return 'copilot'

    @override
    def default_route(self) -> ResolvedRoute:
        """Return a default stateless route for the fake runtime."""
        return ResolvedRoute(runtime='copilot')

    @override
    async def check_health(self) -> RuntimeHealth:
        """Return a healthy fake runtime payload for internal diagnostics."""
        return RuntimeHealth(runtime='copilot', available=True, detail='ok')

    @override
    async def list_model_ids(
        self,
        *,
        runtime_auth_token: str | None = None,
    ) -> tuple[str, ...]:
        """Return a deterministic live-model snapshot for the route."""
        del runtime_auth_token
        return ('claude-sonnet-4.6', 'claude-haiku-3.5')

    @override
    async def complete_chat(self, **kwargs: object) -> RuntimeCompletion:
        """Reject unexpected execution calls in the models contract test."""
        del kwargs
        raise AssertionError('complete_chat should not be called in this test')

    @override
    async def stream_chat(self, **kwargs: object) -> RuntimeEventStream:
        """Reject unexpected streaming calls in the models contract test."""
        del kwargs
        raise AssertionError('stream_chat should not be called in this test')

    @override
    async def discard_interactive_session(
        self,
        *,
        session_id: str,
        disconnect: bool,
    ) -> None:
        """Reject unexpected runtime cleanup calls in the models contract test."""
        del session_id, disconnect
        raise AssertionError(
            'discard_interactive_session should not be called in this test'
        )


class _FakeAnthropicMetadataModelsRuntime(_FakeAnthropicModelsRuntime):
    """Deterministic runtime that exposes metadata-rich Anthropic model cards."""

    @override
    async def list_models(
        self,
        *,
        runtime_auth_token: str | None = None,
    ) -> tuple[RuntimeDiscoveredModel, ...]:
        """Return one metadata-rich live-model snapshot for the route."""
        del runtime_auth_token
        return (
            RuntimeDiscoveredModel(
                id='claude-opus-4.6-1m',
                copilot=CopilotModelMetadata(
                    name='Claude Opus 4.6 (1M context)(Internal only)',
                    capabilities=CopilotModelCapabilities(
                        limits=CopilotModelLimits(max_context_window_tokens=1000000)
                    ),
                ),
            ),
            RuntimeDiscoveredModel(id='claude-haiku-3.5'),
        )


@pytest.mark.asyncio
async def test_get_models_returns_anthropic_compatible_response() -> None:
    """Verify that ``GET /anthropic/v1/models`` returns the expected Anthropic payload."""
    async with build_async_client(runtime=_FakeAnthropicModelsRuntime()) as client:
        response = await client.get('/anthropic/v1/models')

    assert response.status_code == 200
    assert response.json() == {
        'data': [
            {
                'id': 'claude-sonnet-4.6',
                'type': 'model',
                'display_name': 'Claude Sonnet 4.6',
                'created_at': '1970-01-01T00:00:00Z',
            },
            {
                'id': 'claude-haiku-3.5',
                'type': 'model',
                'display_name': 'Claude Haiku 3.5',
                'created_at': '1970-01-01T00:00:00Z',
            },
        ],
        'first_id': 'claude-sonnet-4.6',
        'has_more': False,
        'last_id': 'claude-haiku-3.5',
    }


@pytest.mark.asyncio
async def test_get_models_includes_copilot_metadata_and_runtime_display_name() -> None:
    """Verify Anthropic models expose copilot metadata and prefer runtime names."""
    async with build_async_client(
        runtime=_FakeAnthropicMetadataModelsRuntime()
    ) as client:
        response = await client.get('/anthropic/v1/models')

    assert response.status_code == 200
    assert response.json() == {
        'data': [
            {
                'id': 'claude-opus-4.6-1m',
                'type': 'model',
                'display_name': 'Claude Opus 4.6 (1M context)(Internal only)',
                'created_at': '1970-01-01T00:00:00Z',
                'max_input_tokens': 1000000,
                'copilot': {
                    'name': 'Claude Opus 4.6 (1M context)(Internal only)',
                    'capabilities': {
                        'limits': {
                            'max_context_window_tokens': 1000000,
                        }
                    },
                },
            },
            {
                'id': 'claude-haiku-3.5',
                'type': 'model',
                'display_name': 'Claude Haiku 3.5',
                'created_at': '1970-01-01T00:00:00Z',
            },
        ],
        'first_id': 'claude-opus-4.6-1m',
        'has_more': False,
        'last_id': 'claude-haiku-3.5',
    }
