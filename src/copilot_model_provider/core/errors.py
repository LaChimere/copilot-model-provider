"""Shared error contracts for the provider scaffold."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from fastapi import FastAPI, Request


class ErrorDetail(BaseModel):
    """Structured detail for a provider error."""

    model_config = ConfigDict(frozen=True)

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ErrorResponse(BaseModel):
    """Top-level OpenAI-style API error response."""

    model_config = ConfigDict(frozen=True)

    error: ErrorDetail


class AnthropicErrorType(StrEnum):
    """Supported Anthropic-compatible error categories."""

    INVALID_REQUEST = 'invalid_request_error'
    AUTHENTICATION = 'authentication_error'
    API = 'api_error'


class AnthropicErrorDetail(BaseModel):
    """Structured detail for an Anthropic-compatible error response."""

    model_config = ConfigDict(frozen=True)

    type: AnthropicErrorType
    message: str = Field(min_length=1)


class AnthropicErrorResponse(BaseModel):
    """Top-level Anthropic-compatible error response."""

    model_config = ConfigDict(frozen=True)

    type: str = 'error'
    error: AnthropicErrorDetail


class ErrorResponseFormat(StrEnum):
    """Select the public error envelope format a caller needs."""

    OPENAI = 'openai'
    ANTHROPIC = 'anthropic'


class ProviderError(Exception):
    """Typed exception for scaffold-level provider failures."""

    def __init__(self, *, code: str, message: str, status_code: int = 500) -> None:
        """Initialize a provider-facing exception with structured metadata.

        Args:
            code: Stable machine-readable error code.
            message: Human-readable error message to surface in API responses.
            status_code: HTTP status code associated with the failure.

        """
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def map_provider_error_to_anthropic_type(*, error: ProviderError) -> AnthropicErrorType:
    """Map an internal provider error onto an Anthropic-compatible error type.

    Args:
        error: Structured provider error raised by the application.

    Returns:
        The Anthropic error category that best matches the current provider error
        code while preserving a conservative ``api_error`` fallback.

    """
    if error.code == 'invalid_authorization_header':
        return AnthropicErrorType.AUTHENTICATION

    if error.code == 'model_not_found':
        return AnthropicErrorType.INVALID_REQUEST

    return AnthropicErrorType.API


def build_error_response(
    error: ProviderError,
    *,
    response_format: ErrorResponseFormat = ErrorResponseFormat.OPENAI,
) -> ErrorResponse | AnthropicErrorResponse:
    """Convert a provider exception into the requested public error envelope.

    Args:
        error: The structured provider exception raised by application code.
        response_format: Public wire format whose error envelope should be used.

    Returns:
        An OpenAI-style or Anthropic-style error response model ready to serialize
        as JSON.

    """
    if response_format is ErrorResponseFormat.ANTHROPIC:
        return AnthropicErrorResponse(
            error=AnthropicErrorDetail(
                type=map_provider_error_to_anthropic_type(error=error),
                message=error.message,
            )
        )

    return ErrorResponse(error=ErrorDetail(code=error.code, message=error.message))


def install_error_handlers(app: FastAPI) -> None:
    """Register scaffold-level exception handlers on the FastAPI app.

    Args:
        app: The application instance that should translate ``ProviderError``
            exceptions into the shared JSON error payload.

    """

    async def _handle_provider_error(
        _request: Request,
        error: Exception,
    ) -> JSONResponse:
        """Serialize provider failures into the shared response shape."""
        if not isinstance(error, ProviderError):
            msg = f'Unexpected exception type: {type(error)!r}'
            raise TypeError(msg)

        payload = build_error_response(error).model_dump()
        return JSONResponse(status_code=error.status_code, content=payload)

    app.add_exception_handler(ProviderError, _handle_provider_error)
