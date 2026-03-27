"""Black-box integration tests for the containerized model listing route."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx


def test_container_serves_auth_context_live_model_catalog(
    integration_client: httpx.Client,
    integration_model_ids: list[str],
) -> None:
    """Verify that the production container serves auth-context live model IDs."""
    response = integration_client.get('/openai/v1/models')

    assert response.status_code == 200
    payload = response.json()
    assert payload['object'] == 'list'
    assert [item['id'] for item in payload['data']] == integration_model_ids
