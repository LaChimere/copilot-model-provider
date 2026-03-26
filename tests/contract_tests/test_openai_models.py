"""Contract tests for the OpenAI-compatible model catalog endpoint."""

from __future__ import annotations

import pytest

from tests.harness import build_async_client


@pytest.mark.asyncio
async def test_get_models_returns_openai_compatible_response() -> None:
    """Verify that ``GET /v1/models`` returns the expected OpenAI-style payload."""
    async with build_async_client() as client:
        response = await client.get('/v1/models')

    assert response.status_code == 200
    assert response.json() == {
        'object': 'list',
        'data': [
            {
                'id': 'default',
                'object': 'model',
                'created': 0,
                'owned_by': 'copilot-model-provider',
            },
            {
                'id': 'fast',
                'object': 'model',
                'created': 0,
                'owned_by': 'copilot-model-provider',
            },
        ],
    }
