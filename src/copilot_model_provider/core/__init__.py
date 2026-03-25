"""Core contracts for the provider scaffold."""

from .errors import ErrorDetail, ErrorResponse, ProviderError, install_error_handlers
from .models import (
    CanonicalRequest,
    InternalHealthResponse,
    ResolvedRoute,
    RuntimeHealth,
)

__all__ = [
    'CanonicalRequest',
    'ErrorDetail',
    'ErrorResponse',
    'InternalHealthResponse',
    'ProviderError',
    'ResolvedRoute',
    'RuntimeHealth',
    'install_error_handlers',
]
