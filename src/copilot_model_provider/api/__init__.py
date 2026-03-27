"""Compatibility-layer HTTP routes for the provider service."""

from .anthropic_messages import (
    install_anthropic_count_tokens_route,
    install_anthropic_messages_route,
)
from .openai_models import install_openai_models_route

__all__ = [
    'install_anthropic_count_tokens_route',
    'install_anthropic_messages_route',
    'install_openai_models_route',
]
