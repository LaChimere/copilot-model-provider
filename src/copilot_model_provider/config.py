"""Configuration for the service scaffold."""

from __future__ import annotations

import os
from typing import ClassVar, Literal, Self

from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

EnvironmentName = Literal['development', 'test', 'production']
MIN_SERVER_PORT = 1
MAX_SERVER_PORT = 65535


class ProviderSettings(BaseSettings):
    """Environment-backed configuration for the provider service scaffold."""

    env_prefix: ClassVar[str] = 'COPILOT_MODEL_PROVIDER_'

    model_config = SettingsConfigDict(
        env_prefix=env_prefix,
        extra='ignore',
        frozen=True,
    )

    app_name: str = 'copilot-model-provider'
    environment: EnvironmentName = 'development'
    server_host: str = '127.0.0.1'
    server_port: int = 8000
    enable_internal_health: bool = True
    internal_health_path: str = '/_internal/health'
    default_runtime: str = 'copilot'
    runtime_timeout_seconds: float = 60.0
    runtime_working_directory: str | None = None
    runtime_auth_token: str | None = None

    @field_validator('internal_health_path')
    @classmethod
    def _validate_internal_health_path(
        cls,
        value: str,
        _info: ValidationInfo,
    ) -> str:
        """Ensure the internal health route stays absolute for FastAPI routing."""
        if not value.startswith('/'):
            msg = 'internal_health_path must start with "/"'
            raise ValueError(msg)

        return value

    @field_validator('server_host')
    @classmethod
    def _validate_server_host(
        cls,
        value: str,
        _info: ValidationInfo,
    ) -> str:
        """Ensure the configured bind host is present after normalization."""
        normalized_value = value.strip()
        if not normalized_value:
            msg = 'server_host must not be empty'
            raise ValueError(msg)

        return normalized_value

    @field_validator('server_port')
    @classmethod
    def _validate_server_port(
        cls,
        value: int,
        _info: ValidationInfo,
    ) -> int:
        """Ensure the configured bind port stays within the TCP port range."""
        if value < MIN_SERVER_PORT or value > MAX_SERVER_PORT:
            msg = f'server_port must be between {MIN_SERVER_PORT} and {MAX_SERVER_PORT}'
            raise ValueError(msg)

        return value

    @field_validator('runtime_timeout_seconds')
    @classmethod
    def _validate_runtime_timeout_seconds(
        cls,
        value: float,
        _info: ValidationInfo,
    ) -> float:
        """Ensure the runtime request timeout stays strictly positive."""
        if value <= 0:
            msg = 'runtime_timeout_seconds must be greater than 0'
            raise ValueError(msg)

        return value

    @field_validator('runtime_auth_token')
    @classmethod
    def _normalize_runtime_auth_token(
        cls,
        value: str | None,
        _info: ValidationInfo,
    ) -> str | None:
        """Normalize optional runtime auth tokens so blank values become ``None``."""
        if value is None:
            return None

        normalized_value = value.strip()
        return normalized_value or None

    @classmethod
    def _resolve_host_runtime_auth_token(cls) -> str | None:
        """Resolve the host-provided GitHub token for Docker-oriented deployments.

        Returns:
            The stripped token from ``GITHUB_TOKEN`` or ``GH_TOKEN`` when either
            variable is present with non-whitespace text, otherwise ``None``.

        """
        for variable_name in ('GITHUB_TOKEN', 'GH_TOKEN'):
            token = os.environ.get(variable_name, '').strip()
            if token:
                return token

        return None

    @classmethod
    def from_env(cls) -> Self:
        """Build validated settings from ``COPILOT_MODEL_PROVIDER_*`` variables.

        The method delegates environment resolution to ``pydantic-settings`` so
        field parsing, coercion, and validation all flow through the same model
        definition used for directly constructed settings instances.

        Returns:
            A validated ``ProviderSettings`` instance populated from the current
            process environment.

        """
        settings = cls()
        if settings.runtime_auth_token is not None:
            return settings

        fallback_runtime_auth_token = cls._resolve_host_runtime_auth_token()
        if fallback_runtime_auth_token is None:
            return settings

        return settings.model_copy(
            update={'runtime_auth_token': fallback_runtime_auth_token}
        )
