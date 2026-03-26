"""Black-box integration tests for containerized Responses compatibility."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx


def test_container_responses_non_streaming_supports_live_model_id(
    integration_client: httpx.Client,
    integration_github_token: str,
    integration_model_id: str,
) -> None:
    """Verify that the Responses JSON surface works with one live model ID."""
    response = integration_client.post(
        '/v1/responses',
        headers={'Authorization': f'Bearer {integration_github_token}'},
        json={
            'model': integration_model_id,
            'input': 'Reply with exactly RESPONSES_PING and nothing else.',
            'stream': False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload['object'] == 'response'
    assert payload['model'] == integration_model_id
    assert payload['output'][0]['content'][0]['text'].strip() == 'RESPONSES_PING'


def test_container_responses_streaming_emits_expected_lifecycle(
    integration_client: httpx.Client,
    integration_github_token: str,
    integration_model_id: str,
) -> None:
    """Verify that the containerized SSE stream emits the expected Responses frames."""
    with integration_client.stream(
        'POST',
        '/v1/responses',
        headers={'Authorization': f'Bearer {integration_github_token}'},
        json={
            'model': integration_model_id,
            'input': 'Reply with exactly STREAM_PING and nothing else.',
            'stream': True,
        },
    ) as response:
        assert response.status_code == 200
        assert response.headers['content-type'].startswith('text/event-stream')
        payload = ''.join(response.iter_text())

    assert '"type":"response.created"' in payload
    assert '"type":"response.completed"' in payload
    assert 'STREAM_PING' in payload
