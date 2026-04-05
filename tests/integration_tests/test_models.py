"""Black-box integration tests for the containerized model listing route."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    import httpx


def test_container_serves_auth_context_live_model_catalog(
    integration_client: httpx.Client,
    integration_model_ids: list[str],
) -> None:
    """Verify that the production container serves auth-context live model IDs."""
    response = integration_client.get('/openai/v1/models')

    assert response.status_code == 200
    payload = cast('dict[str, Any]', response.json())
    assert payload['object'] == 'list'
    data = cast('list[dict[str, object]]', payload['data'])
    assert [item['id'] for item in data] == integration_model_ids


def test_container_openai_models_exposes_copilot_metadata(
    integration_client: httpx.Client,
) -> None:
    """Verify the production container exposes additive Copilot metadata."""
    response = integration_client.get('/openai/v1/models')

    assert response.status_code == 200
    payload = cast('dict[str, Any]', response.json())
    data = cast('list[dict[str, object]]', payload['data'])
    copilot_entries: list[dict[str, object]] = []
    for item in data:
        raw_copilot = item.get('copilot')
        if isinstance(raw_copilot, dict):
            copilot_entries.append(cast('dict[str, object]', raw_copilot))

    assert copilot_entries
    assert all(entry for entry in copilot_entries)
    assert any(
        'name' in entry
        or 'capabilities' in entry
        or 'policy' in entry
        or 'billing' in entry
        or 'supported_reasoning_efforts' in entry
        or 'default_reasoning_effort' in entry
        for entry in copilot_entries
    )


def test_container_anthropic_models_exposes_matching_copilot_metadata(
    integration_client: httpx.Client,
) -> None:
    """Verify the Anthropic facade exposes the same additive Copilot metadata."""
    openai_response = integration_client.get('/openai/v1/models')
    response = integration_client.get('/anthropic/v1/models')

    assert openai_response.status_code == 200
    assert response.status_code == 200
    openai_payload = cast('dict[str, Any]', openai_response.json())
    payload = cast('dict[str, Any]', response.json())
    openai_data = cast('list[dict[str, object]]', openai_payload['data'])
    data = cast('list[dict[str, object]]', payload['data'])
    assert [item['id'] for item in data] == [item['id'] for item in openai_data]
    copilot_entries: list[dict[str, object]] = []
    for item in data:
        raw_copilot = item.get('copilot')
        if isinstance(raw_copilot, dict):
            copilot_entries.append(cast('dict[str, object]', raw_copilot))

    assert copilot_entries
    assert all(entry for entry in copilot_entries)
    assert any(
        'name' in entry
        or 'capabilities' in entry
        or 'policy' in entry
        or 'billing' in entry
        or 'supported_reasoning_efforts' in entry
        or 'default_reasoning_effort' in entry
        for entry in copilot_entries
    )
    anthropic_by_id = {cast('str', item['id']): item for item in data}
    for openai_item in openai_data:
        raw_copilot = openai_item.get('copilot')
        if not isinstance(raw_copilot, dict):
            continue
        typed_copilot = cast('dict[str, object]', raw_copilot)
        capabilities = typed_copilot.get('capabilities')
        if not isinstance(capabilities, dict):
            continue
        typed_capabilities = cast('dict[str, object]', capabilities)
        limits = typed_capabilities.get('limits')
        if not isinstance(limits, dict):
            continue
        typed_limits = cast('dict[str, object]', limits)
        max_context_window_tokens = typed_limits.get('max_context_window_tokens')
        if not isinstance(max_context_window_tokens, int):
            continue
        anthropic_item = anthropic_by_id[cast('str', openai_item['id'])]
        assert anthropic_item['max_input_tokens'] == max_context_window_tokens
