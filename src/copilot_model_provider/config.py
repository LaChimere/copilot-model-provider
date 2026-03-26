"""Configuration for the service scaffold."""

from __future__ import annotations

from typing import ClassVar, Literal, Self

from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .tools import (
    MCPServerDefinition,  # noqa: TC001 - needed for pydantic model parsing
)

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
    runtime_cli_url: str | None = None
    mcp_servers: tuple[MCPServerDefinition, ...] = ()

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

    @field_validator('mcp_servers')
    @classmethod
    def _validate_mcp_servers(
        cls,
        value: tuple[MCPServerDefinition, ...],
        _info: ValidationInfo,
    ) -> tuple[MCPServerDefinition, ...]:
        """Ensure configured MCP server names stay unique."""
        names = [server.name for server in value]
        if len(set(names)) != len(names):
            msg = 'mcp_servers must use unique server names'
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

    @field_validator('runtime_cli_url')
    @classmethod
    def _validate_runtime_cli_url(
        cls,
        value: str | None,
        _info: ValidationInfo,
    ) -> str | None:
        """Ensure the optional external CLI URL is either absent or non-empty.

        The Copilot SDK accepts multiple URL forms for external servers
        (``host:port``, ``http://host:port``, or just ``port``), so this
        validator only normalizes surrounding whitespace and rejects empty
        values instead of enforcing a stricter URL format.

        """
        if value is None:
            return None

        normalized_value = value.strip()
        if not normalized_value:
            msg = 'runtime_cli_url must not be empty when provided'
            raise ValueError(msg)

        return normalized_value

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
        return cls()
