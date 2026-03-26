"""Black-box integration tests for the containerized model listing route."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx


def test_container_serves_default_model_catalog(
    integration_client: httpx.Client,
) -> None:
    """Verify that the production container serves the shipped model aliases."""
    response = integration_client.get('/v1/models')

    assert response.status_code == 200
    payload = response.json()
    assert payload['object'] == 'list'
    assert [item['id'] for item in payload['data']] == ['default', 'fast']
