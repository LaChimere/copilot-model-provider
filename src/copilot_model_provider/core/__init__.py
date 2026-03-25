"""Core contracts for the provider scaffold."""

from .catalog import ModelCatalog, create_default_model_catalog
from .errors import ErrorDetail, ErrorResponse, ProviderError, install_error_handlers
from .models import (
    CanonicalRequest,
    InternalHealthResponse,
    ModelCatalogEntry,
    OpenAIModelCard,
    OpenAIModelListResponse,
    ResolvedRoute,
    RuntimeHealth,
)
from .routing import ModelRouter

__all__ = [
    'CanonicalRequest',
    'ErrorDetail',
    'ErrorResponse',
    'InternalHealthResponse',
    'ModelCatalog',
    'ModelCatalogEntry',
    'ModelRouter',
    'OpenAIModelCard',
    'OpenAIModelListResponse',
    'ProviderError',
    'ResolvedRoute',
    'RuntimeHealth',
    'create_default_model_catalog',
    'install_error_handlers',
]
