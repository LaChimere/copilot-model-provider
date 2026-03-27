"""OpenAI-compatible HTTP route installers."""

from .chat import install_openai_chat_route
from .models import install_openai_models_route
from .responses import install_openai_responses_route

__all__ = [
    'install_openai_chat_route',
    'install_openai_models_route',
    'install_openai_responses_route',
]
