"""Compatibility-layer HTTP routes for the provider service."""

from .openai_models import install_openai_models_route

__all__ = ['install_openai_models_route']
