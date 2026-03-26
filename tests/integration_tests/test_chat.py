"""Black-box integration tests for containerized chat completions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx


def test_container_chat_completion_supports_live_model_id(
    integration_client: httpx.Client,
    integration_github_token: str,
    integration_model_id: str,
) -> None:
    """Verify that one live model ID completes through the real container runtime."""
    response = integration_client.post(
        '/v1/chat/completions',
        headers={'Authorization': f'Bearer {integration_github_token}'},
        json={
            'model': integration_model_id,
            'messages': [
                {
                    'role': 'user',
                    'content': 'Reply with exactly DEFAULT_PING and nothing else.',
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload['object'] == 'chat.completion'
    assert payload['model'] == integration_model_id
    assert payload['choices'][0]['message']['content'].strip() == 'DEFAULT_PING'


def test_container_chat_completion_rejects_unknown_model_id(
    integration_client: httpx.Client,
    integration_github_token: str,
) -> None:
    """Verify that unknown live model IDs fail with the structured error contract."""
    response = integration_client.post(
        '/v1/chat/completions',
        headers={'Authorization': f'Bearer {integration_github_token}'},
        json={
            'model': 'missing-model-id',
            'messages': [
                {
                    'role': 'user',
                    'content': 'Reply with exactly FAST_PING and nothing else.',
                }
            ],
        },
    )

    assert response.status_code == 404
    assert response.json()['error']['code'] == 'model_not_found'
