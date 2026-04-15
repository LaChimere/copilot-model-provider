"""Unit tests for the Codex config updater helper."""

from __future__ import annotations

import tomllib

import pytest

from scripts.config_codex import ConfigCodexError, update_codex_config_text


def test_update_codex_config_rewrites_only_root_level_keys() -> None:
    """Verify that nested ``model`` keys survive while root keys are replaced."""
    source = """# Existing Codex config

model = "old-model"
model_provider = "old-provider"
approval_policy = "on-failure"

[features]
model = "leave-this-alone"
"""

    updated = update_codex_config_text(
        source,
        model='gpt-5.4',
        provider_id='copilot-model-provider-local',
        base_url='http://127.0.0.1:8000/openai/v1',
    )
    payload = tomllib.loads(updated)

    assert payload['model'] == 'gpt-5.4'
    assert payload['model_provider'] == 'copilot-model-provider-local'
    assert payload['approval_policy'] == 'on-failure'
    assert payload['features']['model'] == 'leave-this-alone'
    assert updated.count('model = "gpt-5.4"') == 1
    assert updated.count('model_provider = "copilot-model-provider-local"') == 1


def test_update_codex_config_replaces_entire_provider_subtree() -> None:
    """Verify that stale provider subtables are removed before appending the new block."""
    source = """
model = "old-model"
model_provider = "copilot-model-provider-local"

[model_providers."copilot-model-provider-local"]
name = "Stale Local Provider"
base_url = "http://127.0.0.1:9999/openai/v1"

[model_providers."copilot-model-provider-local".headers]
authorization = "Bearer stale"

[[model_providers."copilot-model-provider-local".endpoints]]
path = "/openai/v1/responses"

[mcp_servers.fetch]
enabled = true
"""

    updated = update_codex_config_text(
        source,
        model='gpt-5.4',
        provider_id='copilot-model-provider-local',
        base_url='http://127.0.0.1:8000/openai/v1',
    )
    payload = tomllib.loads(updated)
    provider = payload['model_providers']['copilot-model-provider-local']

    assert provider == {
        'name': 'GitHub Copilot',
        'base_url': 'http://127.0.0.1:8000/openai/v1',
        'wire_api': 'responses',
    }
    assert payload['mcp_servers']['fetch']['enabled'] is True
    assert 'authorization = "Bearer stale"' not in updated
    assert 'path = "/openai/v1/responses"' not in updated


def test_update_codex_config_rejects_invalid_existing_toml() -> None:
    """Verify that malformed input TOML fails fast instead of being rewritten blindly."""
    source = """
model = "first"
model = "second"
"""

    with pytest.raises(ConfigCodexError, match='Invalid existing Codex config'):
        update_codex_config_text(
            source,
            model='gpt-5.4',
            provider_id='copilot-model-provider-local',
            base_url='http://127.0.0.1:8000/openai/v1',
        )
