"""Unit tests for application bootstrapping."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast, override

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from copilot_model_provider.app import create_app
from copilot_model_provider.config import ProviderSettings
from copilot_model_provider.core.models import (
    OpenAIModelCard,
    OpenAIModelListResponse,
    ResolvedRoute,
    RuntimeCompletion,
    RuntimeHealth,
)
from copilot_model_provider.core.routing import ModelRouter, ModelRouterProtocol
from copilot_model_provider.runtimes import CopilotRuntime
from copilot_model_provider.runtimes.protocols import (
    RuntimeEventStream,
    RuntimeProtocol,
)
from tests.harness import build_async_client, build_test_app

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from copilot_model_provider.core.models import InternalHealthResponse


class _FakeModelsRuntime(RuntimeProtocol):
    """Minimal runtime used by app boot tests that hit `/openai/v1/models`."""

    @property
    @override
    def runtime_name(self) -> str:
        """Return the fake runtime name."""
        return 'copilot'

    @override
    def default_route(self) -> ResolvedRoute:
        """Return the fake default route."""
        return ResolvedRoute(runtime='copilot')

    @override
    async def check_health(self) -> RuntimeHealth:
        """Return a healthy fake runtime payload."""
        return RuntimeHealth(runtime='copilot', available=True, detail='ok')

    @override
    async def list_model_ids(
        self,
        *,
        runtime_auth_token: str | None = None,
    ) -> tuple[str, ...]:
        """Return a deterministic live-model snapshot for tests."""
        del runtime_auth_token
        return ('gpt-5.4', 'gpt-5.4-mini')

    @override
    async def complete_chat(self, **kwargs: object) -> RuntimeCompletion:
        """Reject unexpected execution calls in app-boot tests."""
        del kwargs
        raise AssertionError('complete_chat should not be called in this test')

    @override
    async def stream_chat(self, **kwargs: object) -> RuntimeEventStream:
        """Reject unexpected streaming calls in app-boot tests."""
        del kwargs
        raise AssertionError('stream_chat should not be called in this test')


class _StaticModelRouter(ModelRouterProtocol):
    """Deterministic router used when app tests should avoid runtime discovery."""

    @override
    async def list_models_response(
        self,
        *,
        runtime_auth_token: str | None = None,
    ) -> OpenAIModelListResponse:
        """Return a fixed OpenAI-compatible model list."""
        del runtime_auth_token
        return OpenAIModelListResponse(
            data=[
                OpenAIModelCard(
                    id='gpt-5.4',
                    owned_by='copilot-model-provider',
                )
            ]
        )

    @override
    async def resolve_model(
        self,
        *,
        model_id: str,
        runtime_auth_token: str | None = None,
    ) -> ResolvedRoute:
        """Resolve the one supported fake model ID."""
        del runtime_auth_token
        return ResolvedRoute(runtime='copilot', runtime_model_id=model_id)


def _route_paths(app: FastAPI) -> set[str]:
    """Collect registered paths from the FastAPI app."""
    return {route.path for route in app.routes if isinstance(route, APIRoute)}


def test_create_app_returns_fastapi_application() -> None:
    """Verify that ``create_app`` returns a typed FastAPI scaffold instance."""
    app = create_app(settings=ProviderSettings())

    assert isinstance(app, FastAPI)
    assert app.title == 'copilot-model-provider'
    assert isinstance(app.state.model_router, ModelRouter)


def test_internal_health_route_is_optional() -> None:
    """Verify that the internal health route is gated by configuration."""
    enabled_app = create_app(
        settings=ProviderSettings(enable_internal_health=True),
    )
    disabled_app = create_app(
        settings=ProviderSettings(enable_internal_health=False),
    )

    assert '/openai/v1/models' in _route_paths(enabled_app)
    assert '/openai/v1/models' in _route_paths(disabled_app)
    assert '/openai/v1/chat/completions' in _route_paths(enabled_app)
    assert '/openai/v1/chat/completions' in _route_paths(disabled_app)
    assert '/openai/v1/responses' in _route_paths(enabled_app)
    assert '/openai/v1/responses' in _route_paths(disabled_app)
    assert '/anthropic/v1/models' in _route_paths(enabled_app)
    assert '/anthropic/v1/models' in _route_paths(disabled_app)
    assert '/anthropic/v1/messages' in _route_paths(enabled_app)
    assert '/anthropic/v1/messages' in _route_paths(disabled_app)
    assert '/anthropic/v1/messages/count_tokens' in _route_paths(enabled_app)
    assert '/anthropic/v1/messages/count_tokens' in _route_paths(disabled_app)
    assert '/_internal/health' in _route_paths(enabled_app)
    assert '/_internal/health' not in _route_paths(disabled_app)


def test_harness_builds_test_application() -> None:
    """Verify that the harness defaults the app to the test environment."""
    app = build_test_app()

    assert isinstance(app, FastAPI)
    assert app.state.settings.environment == 'test'
    assert isinstance(app.state.model_router, ModelRouter)


def test_create_app_uses_supplied_router_when_router_is_provided() -> None:
    """Verify that app state keeps the injected router instance unchanged."""
    router = _StaticModelRouter()

    app = create_app(
        settings=ProviderSettings(),
        model_router=router,
    )

    assert app.state.model_router is router


def test_protocol_implementations_are_explicitly_declared() -> None:
    """Verify that concrete implementations explicitly inherit their protocols."""
    assert RuntimeProtocol in CopilotRuntime.__bases__
    assert ModelRouterProtocol in ModelRouter.__bases__


class _CapturedLogger:
    """Record structlog-style info and exception calls for request logging tests."""

    def __init__(self) -> None:
        """Initialize the in-memory event sink."""
        self.events: list[tuple[str, dict[str, object]]] = []

    def info(self, event: str, **kwargs: object) -> None:
        """Record one informational log event."""
        self.events.append((event, kwargs))

    def exception(self, event: str, **kwargs: object) -> None:
        """Record one exception log event."""
        self.events.append((event, kwargs))


class _IncompleteRuntime:
    """Deliberately invalid runtime dependency for protocol validation tests."""

    runtime_name = 'broken'


class _IncompleteModelRouter:
    """Deliberately invalid router dependency for protocol validation tests."""

    async def list_models_response(self) -> OpenAIModelListResponse:
        """Return a placeholder model list for protocol validation tests."""
        return OpenAIModelListResponse(data=[])


def test_create_app_rejects_runtime_dependencies_that_fail_protocol_validation() -> (
    None
):
    """Verify that runtime injections must satisfy the explicit runtime protocol."""
    with pytest.raises(TypeError, match='RuntimeProtocol protocol'):
        create_app(
            settings=ProviderSettings(environment='test'),
            runtime=cast('Any', _IncompleteRuntime()),
        )


def test_create_app_rejects_router_dependencies_that_fail_protocol_validation() -> None:
    """Verify that router injections must satisfy the explicit routing protocol."""
    with pytest.raises(TypeError, match='ModelRouterProtocol protocol'):
        create_app(
            settings=ProviderSettings(environment='test'),
            model_router=cast('Any', _IncompleteModelRouter()),
        )


@pytest.mark.asyncio
async def test_request_logging_middleware_emits_structured_completion_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that HTTP requests are logged through the structlog middleware."""
    import importlib

    app_module = importlib.import_module('copilot_model_provider.app')

    captured_logger = _CapturedLogger()
    monkeypatch.setattr(app_module, '_logger', captured_logger)

    async with build_async_client(
        runtime=_FakeModelsRuntime(),
        model_router=_StaticModelRouter(),
    ) as client:
        response = await client.get('/openai/v1/models')

    assert response.status_code == 200
    completion_events = [
        fields
        for event, fields in captured_logger.events
        if event == 'http_request_completed'
    ]
    assert len(completion_events) == 1
    assert completion_events[0]['method'] == 'GET'
    assert completion_events[0]['path'] == '/openai/v1/models'
    assert completion_events[0]['status_code'] == 200


@pytest.mark.asyncio
async def test_request_validation_failures_emit_structured_body_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that request-validation failures log structural request details."""
    import importlib

    errors_module = importlib.import_module('copilot_model_provider.core.errors')

    captured_logger = _CapturedLogger()
    monkeypatch.setattr(errors_module, '_logger', captured_logger)
    request_json: dict[str, object] = {
        'model': 'gpt-5.4',
        'stream': True,
        'previous_response_id': 'resp_test',
        'input': [
            {
                'type': 'function_call_output',
                'call_id': 'call_123',
                'output': {'status': 'ok'},
            },
            {
                'type': 'reasoning',
                'summary': [],
            },
        ],
    }

    async with build_async_client(
        runtime=_FakeModelsRuntime(),
        model_router=_StaticModelRouter(),
    ) as client:
        response = await client.post(
            '/openai/v1/responses',
            json=request_json,
        )

    assert response.status_code == 422
    validation_events = [
        fields
        for event, fields in captured_logger.events
        if event == 'request_validation_failed'
    ]
    assert len(validation_events) == 1
    assert validation_events[0]['path'] == '/openai/v1/responses'
    assert validation_events[0]['body_summary'] == {
        'body_type': 'dict',
        'body_keys': ['input', 'model', 'previous_response_id', 'stream'],
        'model': 'gpt-5.4',
        'stream': True,
        'previous_response_id': 'resp_test',
        'instructions_kind': 'none',
        'input_kind': 'list',
        'input_item_types': ['function_call_output', 'reasoning'],
        'input_item_keys': [
            ['call_id', 'output', 'type'],
            ['summary', 'type'],
        ],
        'tool_output_types': ['dict'],
        'tool_count': None,
    }
    validation_errors = cast('list[dict[str, object]]', validation_events[0]['errors'])
    assert any(
        isinstance((loc := error.get('loc')), list) and loc[0:2] == ['body', 'input']
        for error in validation_errors
    )


@pytest.mark.asyncio
async def test_internal_health_handler_returns_scaffold_payload() -> None:
    """Verify that the internal health handler reports lazy Copilot state."""
    app = create_app(settings=ProviderSettings(environment='test'))
    endpoint = _resolve_endpoint(app, '/_internal/health')
    response: InternalHealthResponse = await endpoint()

    assert response.status == 'ok'
    assert response.service == 'copilot-model-provider'
    assert response.environment == 'test'
    assert response.runtime.runtime == 'copilot'
    assert response.runtime.available is False
    assert response.runtime.detail == 'Copilot client state: disconnected'


def _resolve_endpoint(
    app: FastAPI,
    path: str,
) -> Callable[[], Awaitable[InternalHealthResponse]]:
    """Find the callable endpoint for a registered route."""
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == path:
            return route.endpoint

    msg = f'Unable to find route for path {path!r}'
    raise AssertionError(msg)
