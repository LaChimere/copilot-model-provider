"""Configuration for the service scaffold."""

from __future__ import annotations

from typing import ClassVar, Literal, Self

from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

EnvironmentName = Literal['development', 'test', 'production']


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
    enable_internal_health: bool = True
    internal_health_path: str = '/_internal/health'
    default_runtime: str = 'copilot'

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
