"""Unit tests for shared error contracts."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

import pytest
from fastapi import FastAPI
from starlette.requests import Request

from copilot_model_provider.core.errors import (
    ProviderError,
    build_error_response,
    install_error_handlers,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastapi.responses import JSONResponse

    type ExceptionHandler = Callable[[Request, Exception], Awaitable[JSONResponse]]


def test_build_error_response_serializes_provider_error() -> None:
    """Verify that provider errors are converted into the shared JSON envelope."""
    error = ProviderError(code='bad_request', message='Nope', status_code=400)

    response = build_error_response(error)

    assert response.error.code == 'bad_request'
    assert response.error.message == 'Nope'


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
async def test_install_error_handlers_rejects_unexpected_exception_types() -> None:
    """Verify that the provider handler fails loudly on unexpected exceptions."""
    app = FastAPI()
    install_error_handlers(app)
    handler = cast('ExceptionHandler', app.exception_handlers[ProviderError])
    request = _build_request()

    with pytest.raises(TypeError, match='Unexpected exception type'):
        await handler(request, Exception('boom'))


def _build_request() -> Request:
    """Construct a minimal Starlette request object for handler tests."""
    return Request(
        {
            'type': 'http',
            'http_version': '1.1',
            'method': 'GET',
            'scheme': 'http',
            'path': '/',
            'raw_path': b'/',
            'query_string': b'',
            'root_path': '',
            'headers': [],
            'client': ('127.0.0.1', 12345),
            'server': ('testserver', 80),
        }
    )
