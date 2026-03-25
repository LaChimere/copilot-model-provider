"""Lightweight integration smoke tests for the model catalog route."""

from __future__ import annotations

import pytest

from tests.integration_tests.harness import build_async_client


@pytest.mark.asyncio
async def test_model_catalog_smoke_path_boots_and_serves_models() -> None:
    """Verify that the in-process app boots and serves the model list over HTTP."""
    async with build_async_client() as client:
        response = await client.get('/v1/models')

    assert response.status_code == 200
    payload = response.json()
    assert payload['object'] == 'list'
    assert [item['id'] for item in payload['data']] == ['default', 'fast']
