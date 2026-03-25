"""Lightweight integration smoke tests for the non-streaming chat route."""

from __future__ import annotations

from typing import override

import pytest

from copilot_model_provider.core.models import (
    CanonicalChatRequest,
    ResolvedRoute,
    RuntimeCompletion,
    RuntimeHealth,
)
from copilot_model_provider.runtimes.base import RuntimeAdapter
from tests.integration_tests.harness import build_async_client


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
