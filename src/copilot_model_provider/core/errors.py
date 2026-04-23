"""Shared error contracts for the provider scaffold."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, cast

import structlog
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from fastapi import FastAPI, Request

_logger = structlog.get_logger(__name__)


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

    if error.code in {'model_not_found', 'continuation_expired'}:
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
        request: Request,
        error: Exception,
    ) -> JSONResponse:
        """Serialize provider failures into the shared response shape."""
        if not isinstance(error, ProviderError):
            msg = f'Unexpected exception type: {type(error)!r}'
            raise TypeError(msg)

        response_format = (
            ErrorResponseFormat.ANTHROPIC
            if request.url.path.startswith('/anthropic/')
            else ErrorResponseFormat.OPENAI
        )
        payload = build_error_response(
            error,
            response_format=response_format,
        ).model_dump(mode='json')
        return JSONResponse(status_code=error.status_code, content=payload)

    async def _handle_request_validation_error(
        request: Request,
        error: Exception,
    ) -> JSONResponse:
        """Log request-validation failures and preserve FastAPI's 422 response body."""
        if not isinstance(error, RequestValidationError):
            msg = f'Unexpected exception type: {type(error)!r}'
            raise TypeError(msg)

        _logger.info(
            'request_validation_failed',
            method=request.method,
            path=request.url.path,
            query=request.url.query or None,
            errors=_summarize_validation_errors(
                errors=cast('list[object]', error.errors())
            ),
            body_summary=_summarize_validation_body(
                path=request.url.path,
                body=error.body,
            ),
        )
        return JSONResponse(
            status_code=422,
            content={'detail': error.errors()},
        )

    app.add_exception_handler(ProviderError, _handle_provider_error)
    app.add_exception_handler(RequestValidationError, _handle_request_validation_error)


def _summarize_validation_errors(*, errors: list[object]) -> list[dict[str, object]]:
    """Return a compact, log-friendly summary of validation errors."""
    summarized_errors: list[dict[str, object]] = []
    for error in errors:
        if not isinstance(error, dict):
            continue
        typed_error = cast('dict[str, object]', error)
        loc = typed_error.get('loc')
        loc_summary: list[object]
        if isinstance(loc, list):
            loc_summary = list(cast('list[object]', loc))
        elif isinstance(loc, tuple):
            loc_summary = [*loc]
        else:
            loc_summary = []
        summarized_errors.append(
            {
                'type': typed_error.get('type'),
                'loc': loc_summary,
                'msg': typed_error.get('msg'),
            }
        )
    return summarized_errors


def _summarize_validation_body(*, path: str, body: object) -> dict[str, object]:
    """Return a structural summary of the rejected request body."""
    if path == '/openai/v1/responses':
        return _summarize_openai_responses_validation_body(body=body)
    return _summarize_generic_validation_body(body=body)


def _summarize_openai_responses_validation_body(*, body: object) -> dict[str, object]:
    """Return a safe structural summary for invalid Responses request bodies."""
    summary = _summarize_generic_validation_body(body=body)
    if not isinstance(body, dict):
        return summary

    typed_body = cast('dict[str, object]', body)
    input_value = typed_body.get('input')
    input_item_types: list[object] = []
    input_item_keys: list[list[str]] = []
    tool_output_types: list[str | None] = []
    if isinstance(input_value, list):
        for item in cast('list[object]', input_value)[:20]:
            if not isinstance(item, dict):
                input_item_types.append(type(item).__name__)
                continue
            typed_item = cast('dict[str, object]', item)
            input_item_types.append(typed_item.get('type'))
            input_item_keys.append(sorted(typed_item))
            if typed_item.get('type') == 'function_call_output':
                output_value = typed_item.get('output')
                tool_output_types.append(type(output_value).__name__)

    tools_value = typed_body.get('tools')
    input_kind = (
        'list' if isinstance(input_value, list) else _classify_body_shape(input_value)
    )
    summary.update(
        {
            'model': typed_body.get('model'),
            'stream': typed_body.get('stream'),
            'previous_response_id': typed_body.get('previous_response_id'),
            'instructions_kind': _classify_body_shape(typed_body.get('instructions')),
            'input_kind': input_kind,
            'input_item_types': input_item_types,
            'input_item_keys': input_item_keys,
            'tool_output_types': tool_output_types,
            'tool_count': len(cast('list[object]', tools_value))
            if isinstance(tools_value, list)
            else None,
        }
    )
    return summary


def _summarize_generic_validation_body(*, body: object) -> dict[str, object]:
    """Return a generic summary for invalid request bodies."""
    if isinstance(body, dict):
        typed_body = cast('dict[str, object]', body)
        return {
            'body_type': 'dict',
            'body_keys': sorted(typed_body),
        }
    if isinstance(body, list):
        return {
            'body_type': 'list',
            'body_length': len(cast('list[object]', body)),
        }
    if body is None:
        return {'body_type': 'none'}
    return {'body_type': type(body).__name__}


def _classify_body_shape(value: object) -> str:
    """Classify the top-level shape of one body field for diagnostic logging."""
    if value is None:
        return 'none'
    if isinstance(value, str):
        return 'string'
    if isinstance(value, list):
        return 'list'
    if isinstance(value, dict):
        return 'dict'
    return type(value).__name__
