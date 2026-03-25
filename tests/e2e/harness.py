"""Helpers for end-to-end style scaffold checks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from copilot_model_provider.app import create_app
from copilot_model_provider.config import ProviderSettings

if TYPE_CHECKING:
    from fastapi import FastAPI


def build_test_app(*, settings: ProviderSettings | None = None) -> FastAPI:
    """Build the scaffold app with test-friendly defaults.

    Args:
        settings: Optional settings override for specialized test scenarios.

    Returns:
        A FastAPI app configured the same way production code builds it, but
        defaulting the environment to ``test`` when no settings are provided.

    """
    resolved_settings = settings or ProviderSettings(environment='test')
    return create_app(settings=resolved_settings)
