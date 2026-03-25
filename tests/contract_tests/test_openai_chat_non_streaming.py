"""Contract tests for the OpenAI-compatible non-streaming chat endpoint."""

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


class _FakeChatRuntimeAdapter(RuntimeAdapter):
    """Deterministic runtime adapter used by HTTP contract tests."""

    def __init__(self) -> None:
        """Initialize the fake runtime with a stable Copilot name."""
        super().__init__(runtime_name='copilot')

    @override
    def default_route(self) -> ResolvedRoute:
        """Return a default stateless route for the fake runtime."""
        return ResolvedRoute(runtime='copilot', session_mode='stateless')

    @override
    async def check_health(self) -> RuntimeHealth:
        """Return a healthy fake runtime payload for internal diagnostics."""
        return RuntimeHealth(runtime='copilot', available=True, detail='ok')

    @override
    async def complete_chat(
        self,
        *,
        request: CanonicalChatRequest,
        route: ResolvedRoute,
    ) -> RuntimeCompletion:
        """Return a deterministic non-streaming completion for HTTP tests."""
        del request, route
        return RuntimeCompletion(
            output_text='Hello from the fake runtime.',
            provider_response_id='chatcmpl-contract',
            prompt_tokens=9,
            completion_tokens=6,
        )


@pytest.mark.asyncio
async def test_post_chat_completions_returns_openai_compatible_payload() -> None:
    """Verify that the HTTP route returns the expected non-streaming payload."""
    async with build_async_client(runtime_adapter=_FakeChatRuntimeAdapter()) as client:
        response = await client.post(
            '/v1/chat/completions',
            json={
                'model': 'default',
                'messages': [{'role': 'user', 'content': 'Hello'}],
            },
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload['id'] == 'chatcmpl-contract'
    assert payload['object'] == 'chat.completion'
    assert isinstance(payload['created'], int)
    assert payload['model'] == 'default'
    assert payload['choices'] == [
        {
            'index': 0,
            'message': {
                'role': 'assistant',
                'content': 'Hello from the fake runtime.',
            },
            'finish_reason': 'stop',
        }
    ]
    assert payload['usage'] == {
        'prompt_tokens': 9,
        'completion_tokens': 6,
        'total_tokens': 15,
    }


@pytest.mark.asyncio
async def test_post_chat_completions_rejects_streaming_requests() -> None:
    """Verify that unsupported streaming requests use the shared error envelope."""
    async with build_async_client(runtime_adapter=_FakeChatRuntimeAdapter()) as client:
        response = await client.post(
            '/v1/chat/completions',
            json={
                'model': 'default',
                'stream': True,
                'messages': [{'role': 'user', 'content': 'Hello'}],
            },
        )

    assert response.status_code == 400
    assert response.json() == {
        'error': {
            'code': 'streaming_not_supported',
            'message': 'Streaming chat completions are not implemented yet.',
        }
    }
