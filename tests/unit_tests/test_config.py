"""Unit tests for service configuration."""

from __future__ import annotations

import os
from typing import Any, cast
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from copilot_model_provider.config import ProviderSettings


def test_defaults_are_stable() -> None:
    """Verify that direct construction preserves the documented defaults."""
    settings = ProviderSettings()

    assert settings.app_name == 'copilot-model-provider'
    assert settings.environment == 'development'
    assert settings.enable_internal_health is True
    assert settings.internal_health_path == '/_internal/health'
    assert settings.default_runtime == 'copilot'


def test_from_env_reads_overrides() -> None:
    """Verify that supported environment variables override default settings."""
    env = {
        'COPILOT_MODEL_PROVIDER_APP_NAME': 'cmp-test',
        'COPILOT_MODEL_PROVIDER_ENVIRONMENT': 'test',
        'COPILOT_MODEL_PROVIDER_ENABLE_INTERNAL_HEALTH': 'false',
        'COPILOT_MODEL_PROVIDER_INTERNAL_HEALTH_PATH': '/_healthz',
        'COPILOT_MODEL_PROVIDER_DEFAULT_RUNTIME': 'custom-runtime',
    }

    with patch.dict(os.environ, env, clear=False):
        settings = ProviderSettings.from_env()

    assert settings.app_name == 'cmp-test'
    assert settings.environment == 'test'
    assert settings.enable_internal_health is False
    assert settings.internal_health_path == '/_healthz'
    assert settings.default_runtime == 'custom-runtime'


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
