"""Shared error contracts for the provider scaffold."""

from __future__ import annotations

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
    """Top-level API error response."""

    model_config = ConfigDict(frozen=True)

    error: ErrorDetail


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


def build_error_response(error: ProviderError) -> ErrorResponse:
    """Convert a provider exception into the repository's error envelope.

    Args:
        error: The structured provider exception raised by application code.

    Returns:
        An ``ErrorResponse`` instance ready to serialize as JSON.

    """
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
