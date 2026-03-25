"""Top-level package for the copilot model provider project."""

from .app import app, create_app
from .config import ProviderSettings

__all__ = ['ProviderSettings', 'app', 'create_app']
