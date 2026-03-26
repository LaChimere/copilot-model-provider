"""Unit tests for service configuration."""

from __future__ import annotations

import os
from typing import Any, cast
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from copilot_model_provider.config import ProviderSettings
from copilot_model_provider.tools import MCPServerDefinition


def test_defaults_are_stable() -> None:
    """Verify that direct construction preserves the documented defaults."""
    settings = ProviderSettings()

    assert settings.app_name == 'copilot-model-provider'
    assert settings.environment == 'development'
    assert settings.server_host == '127.0.0.1'
    assert settings.server_port == 8000
    assert settings.enable_internal_health is True
    assert settings.internal_health_path == '/_internal/health'
    assert settings.default_runtime == 'copilot'
    assert settings.runtime_cli_url is None
    assert settings.mcp_servers == ()


def test_from_env_reads_overrides() -> None:
    """Verify that supported environment variables override default settings."""
    env = {
        'COPILOT_MODEL_PROVIDER_APP_NAME': 'cmp-test',
        'COPILOT_MODEL_PROVIDER_ENVIRONMENT': 'test',
        'COPILOT_MODEL_PROVIDER_SERVER_HOST': ' 0.0.0.0 ',
        'COPILOT_MODEL_PROVIDER_SERVER_PORT': '9000',
        'COPILOT_MODEL_PROVIDER_ENABLE_INTERNAL_HEALTH': 'false',
        'COPILOT_MODEL_PROVIDER_INTERNAL_HEALTH_PATH': '/_healthz',
        'COPILOT_MODEL_PROVIDER_DEFAULT_RUNTIME': 'custom-runtime',
        'COPILOT_MODEL_PROVIDER_RUNTIME_CLI_URL': ' http://copilot-cli.internal:3000 ',
        'COPILOT_MODEL_PROVIDER_MCP_SERVERS': (
            '[{"name":"docs-api","transport":"http","url":"http://localhost:8123/mcp"}]'
        ),
    }

    with patch.dict(os.environ, env, clear=False):
        settings = ProviderSettings.from_env()

    assert settings.app_name == 'cmp-test'
    assert settings.environment == 'test'
    assert settings.server_host == '0.0.0.0'  # noqa: S104 - intentional bind-all case
    assert settings.server_port == 9000
    assert settings.enable_internal_health is False
    assert settings.internal_health_path == '/_healthz'
    assert settings.default_runtime == 'custom-runtime'
    assert settings.runtime_cli_url == 'http://copilot-cli.internal:3000'
    assert len(settings.mcp_servers) == 1
    assert settings.mcp_servers[0].name == 'docs-api'


def test_invalid_health_path_raises() -> None:
    """Verify that relative internal health paths are rejected early."""
    with pytest.raises(ValidationError, match='internal_health_path'):
        ProviderSettings(internal_health_path='health')


def test_invalid_environment_raises() -> None:
    """Verify that unsupported environment names are rejected during validation."""
    invalid_environment = cast('Any', 'staging')

    with pytest.raises(ValidationError, match='environment'):
        ProviderSettings(environment=invalid_environment)


def test_from_env_accepts_production_and_truthy_boolean_values() -> None:
    """Verify that production mode and truthy boolean env values are parsed correctly."""
    env = {
        'COPILOT_MODEL_PROVIDER_ENVIRONMENT': 'production',
        'COPILOT_MODEL_PROVIDER_ENABLE_INTERNAL_HEALTH': 'yes',
    }

    with patch.dict(os.environ, env, clear=False):
        settings = ProviderSettings.from_env()

    assert settings.environment == 'production'
    assert settings.enable_internal_health is True


def test_from_env_rejects_invalid_boolean_values() -> None:
    """Verify that unsupported boolean env values fail fast during parsing."""
    env = {
        'COPILOT_MODEL_PROVIDER_ENABLE_INTERNAL_HEALTH': 'sometimes',
    }

    with (
        patch.dict(os.environ, env, clear=False),
        pytest.raises(ValidationError, match='enable_internal_health'),
    ):
        ProviderSettings.from_env()


def test_from_env_rejects_invalid_environment_values() -> None:
    """Verify that unsupported environment env values fail before app boot."""
    env = {
        'COPILOT_MODEL_PROVIDER_ENVIRONMENT': 'staging',
    }

    with (
        patch.dict(os.environ, env, clear=False),
        pytest.raises(ValidationError, match='environment'),
    ):
        ProviderSettings.from_env()


def test_duplicate_mcp_server_names_are_rejected() -> None:
    """Verify that MCP server configuration fails fast on duplicate names."""
    with pytest.raises(ValidationError, match='mcp_servers'):
        ProviderSettings(
            mcp_servers=(
                MCPServerDefinition(
                    name='docs-api',
                    transport='http',
                    url='http://one',
                ),
                MCPServerDefinition(
                    name='docs-api',
                    transport='http',
                    url='http://two',
                ),
            )
        )


def test_runtime_cli_url_rejects_empty_values() -> None:
    """Verify that an explicitly empty external CLI URL fails validation."""
    with pytest.raises(ValidationError, match='runtime_cli_url'):
        ProviderSettings(runtime_cli_url='   ')


def test_server_host_rejects_empty_values() -> None:
    """Verify that an explicitly empty bind host fails validation."""
    with pytest.raises(ValidationError, match='server_host'):
        ProviderSettings(server_host='   ')


def test_server_port_rejects_invalid_values() -> None:
    """Verify that out-of-range bind ports fail validation."""
    with pytest.raises(ValidationError, match='server_port'):
        ProviderSettings(server_port=0)
