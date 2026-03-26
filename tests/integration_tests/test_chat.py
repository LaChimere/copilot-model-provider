"""Black-box integration tests for containerized chat completions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx


def test_container_chat_completion_supports_default_alias(
    integration_client: httpx.Client,
    integration_github_token: str,
) -> None:
    """Verify that the default alias completes through the real container runtime."""
    response = integration_client.post(
        '/v1/chat/completions',
        headers={'Authorization': f'Bearer {integration_github_token}'},
        json={
            'model': 'default',
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
    assert payload['model'] == 'default'
    assert payload['choices'][0]['message']['content'].strip() == 'DEFAULT_PING'


def test_container_chat_completion_supports_fast_alias(
    integration_client: httpx.Client,
    integration_github_token: str,
) -> None:
    """Verify that the fast alias completes through the real container runtime."""
    response = integration_client.post(
        '/v1/chat/completions',
        headers={'Authorization': f'Bearer {integration_github_token}'},
        json={
            'model': 'fast',
            'messages': [
                {
                    'role': 'user',
                    'content': 'Reply with exactly FAST_PING and nothing else.',
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload['object'] == 'chat.completion'
    assert payload['model'] == 'fast'
    assert payload['choices'][0]['message']['content'].strip() == 'FAST_PING'
