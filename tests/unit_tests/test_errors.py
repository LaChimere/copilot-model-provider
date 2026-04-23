"""Unit tests for shared error contracts."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

import pytest
from fastapi import FastAPI
from starlette.requests import Request

from copilot_model_provider.core.errors import (
    AnthropicErrorResponse,
    AnthropicErrorType,
    ErrorResponse,
    ErrorResponseFormat,
    ProviderError,
    build_error_response,
    install_error_handlers,
    map_provider_error_to_anthropic_type,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastapi.responses import JSONResponse

    type ExceptionHandler = Callable[[Request, Exception], Awaitable[JSONResponse]]


def test_build_error_response_serializes_provider_error() -> None:
    """Verify that provider errors are converted into the shared JSON envelope."""
    error = ProviderError(code='bad_request', message='Nope', status_code=400)

    response = build_error_response(error)

    assert isinstance(response, ErrorResponse)
    assert response.error.code == 'bad_request'
    assert response.error.message == 'Nope'


def test_build_error_response_supports_anthropic_envelope() -> None:
    """Verify that provider errors can be rendered in Anthropic wire format."""
    error = ProviderError(code='model_not_found', message='Missing', status_code=404)

    response = build_error_response(
        error,
        response_format=ErrorResponseFormat.ANTHROPIC,
    )

    assert isinstance(response, AnthropicErrorResponse)
    assert response.type == 'error'
    assert response.error.type is AnthropicErrorType.INVALID_REQUEST
    assert response.error.message == 'Missing'


def test_map_provider_error_to_anthropic_type_uses_conservative_fallbacks() -> None:
    """Verify that Anthropic error typing maps known codes and defaults safely."""
    assert (
        map_provider_error_to_anthropic_type(
            error=ProviderError(
                code='invalid_authorization_header',
                message='Bad auth',
                status_code=400,
            )
        )
        is AnthropicErrorType.AUTHENTICATION
    )
    assert (
        map_provider_error_to_anthropic_type(
            error=ProviderError(
                code='model_not_found',
                message='Unknown model',
                status_code=404,
            )
        )
        is AnthropicErrorType.INVALID_REQUEST
    )
    assert (
        map_provider_error_to_anthropic_type(
            error=ProviderError(
                code='continuation_expired',
                message='Expired continuation',
                status_code=400,
            )
        )
        is AnthropicErrorType.INVALID_REQUEST
    )
    assert (
        map_provider_error_to_anthropic_type(
            error=ProviderError(
                code='runtime_execution_failed',
                message='Boom',
                status_code=500,
            )
        )
        is AnthropicErrorType.API
    )


@pytest.mark.asyncio
async def test_install_error_handlers_registers_provider_handler() -> None:
    """Verify that the installed handler returns the structured JSON payload."""
    app = FastAPI()
    install_error_handlers(app)
    handler = cast('ExceptionHandler', app.exception_handlers[ProviderError])
    request = _build_request()
    error = ProviderError(code='forbidden', message='Denied', status_code=403)

    response = await handler(request, error)

    assert response.status_code == 403
    assert json.loads(bytes(response.body)) == {
        'error': {
            'code': 'forbidden',
            'message': 'Denied',
        }
    }


@pytest.mark.asyncio
async def test_install_error_handlers_uses_anthropic_error_shape_for_anthropic_paths() -> (
    None
):
    """Verify that Anthropic routes receive Anthropic-compatible error envelopes."""
    app = FastAPI()
    install_error_handlers(app)
    handler = cast('ExceptionHandler', app.exception_handlers[ProviderError])
    request = _build_request(path='/anthropic/v1/messages')
    error = ProviderError(
        code='invalid_authorization_header',
        message='Denied',
        status_code=403,
    )

    response = await handler(request, error)

    assert response.status_code == 403
    assert json.loads(bytes(response.body)) == {
        'type': 'error',
        'error': {
            'type': 'authentication_error',
            'message': 'Denied',
        },
    }


@pytest.mark.asyncio
async def test_install_error_handlers_rejects_unexpected_exception_types() -> None:
    """Verify that the provider handler fails loudly on unexpected exceptions."""
    app = FastAPI()
    install_error_handlers(app)
    handler = cast('ExceptionHandler', app.exception_handlers[ProviderError])
    request = _build_request()

    with pytest.raises(TypeError, match='Unexpected exception type'):
        await handler(request, Exception('boom'))


def _build_request(*, path: str = '/') -> Request:
    """Construct a minimal Starlette request object for handler tests."""
    return Request(
        {
            'type': 'http',
            'http_version': '1.1',
            'method': 'GET',
            'scheme': 'http',
            'path': path,
            'raw_path': path.encode(),
            'query_string': b'',
            'root_path': '',
            'headers': [],
            'client': ('127.0.0.1', 12345),
            'server': ('testserver', 80),
        }
    )
