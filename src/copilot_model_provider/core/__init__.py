"""Core contracts for the provider scaffold."""

from .catalog import ModelCatalog, create_default_model_catalog
from .chat import (
    build_openai_chat_completion_response,
    normalize_openai_chat_request,
    render_prompt,
)
from .errors import (
    ErrorDetail,
    ErrorResponse,
    ProviderError,
    install_error_handlers,
)
from .models import (
    CanonicalChatMessage,
    CanonicalChatRequest,
    CanonicalRequest,
    InternalHealthResponse,
    ModelCatalogEntry,
    OpenAIChatCompletionChoice,
    OpenAIChatCompletionRequest,
    OpenAIChatCompletionResponse,
    OpenAIChatMessage,
    OpenAIModelCard,
    OpenAIModelListResponse,
    OpenAIUsage,
    ResolvedRoute,
    RuntimeCompletion,
    RuntimeHealth,
)
from .routing import ModelRouter

__all__ = [
    'CanonicalChatMessage',
    'CanonicalChatRequest',
    'CanonicalRequest',
    'ErrorDetail',
    'ErrorResponse',
    'InternalHealthResponse',
    'ModelCatalog',
    'ModelCatalogEntry',
    'ModelRouter',
    'OpenAIChatCompletionChoice',
    'OpenAIChatCompletionRequest',
    'OpenAIChatCompletionResponse',
    'OpenAIChatMessage',
    'OpenAIModelCard',
    'OpenAIModelListResponse',
    'OpenAIUsage',
    'ProviderError',
    'ResolvedRoute',
    'RuntimeCompletion',
    'RuntimeHealth',
    'build_openai_chat_completion_response',
    'create_default_model_catalog',
    'install_error_handlers',
    'normalize_openai_chat_request',
    'render_prompt',
]
