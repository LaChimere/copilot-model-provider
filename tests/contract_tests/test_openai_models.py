"""Contract tests for the OpenAI-compatible model catalog endpoint."""

from __future__ import annotations

from typing import override

import pytest

from copilot_model_provider.core.models import (
    ResolvedRoute,
    RuntimeCompletion,
    RuntimeHealth,
)
from copilot_model_provider.runtimes.protocols import (
    RuntimeEventStream,
    RuntimeProtocol,
)
from tests.harness import build_async_client


class _FakeModelsRuntime(RuntimeProtocol):
    """Deterministic runtime used by the models contract test."""

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
        return ('gpt-5.4', 'gpt-5.4-mini')

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


@pytest.mark.asyncio
async def test_get_models_returns_openai_compatible_response() -> None:
    """Verify that ``GET /openai/v1/models`` returns the expected OpenAI-style payload."""
    async with build_async_client(runtime=_FakeModelsRuntime()) as client:
        response = await client.get('/openai/v1/models')

    assert response.status_code == 200
    assert response.json() == {
        'object': 'list',
        'data': [
            {
                'id': 'gpt-5.4',
                'object': 'model',
                'created': 0,
                'owned_by': 'copilot-model-provider',
            },
            {
                'id': 'gpt-5.4-mini',
                'object': 'model',
                'created': 0,
                'owned_by': 'copilot-model-provider',
            },
        ],
    }
