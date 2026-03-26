"""Unit tests for service entrypoint helpers."""

from __future__ import annotations

import runpy
from typing import TYPE_CHECKING

from copilot_model_provider import server
from copilot_model_provider.config import ProviderSettings

if TYPE_CHECKING:
    import pytest


def test_build_startup_guidance_describes_service_entrypoint() -> None:
    """Verify that the helper describes the service-first startup model."""
    guidance = server.build_startup_guidance()

    assert 'copilot-model-provider is a service package' in guidance
    assert 'An installed ASGI server such as uvicorn is required' in guidance
    assert 'copilot-model-provider' in guidance
    assert 'uvicorn copilot_model_provider.app:app' in guidance
    assert 'uvicorn copilot_model_provider.app:create_app --factory' in guidance


def test_build_startup_guidance_fields_match_text_guidance() -> None:
    """Verify that structured guidance fields remain aligned with text output."""
    fields = server.build_startup_guidance_fields()
    guidance = server.build_startup_guidance()

    assert fields['summary'] in guidance
    assert fields['asgi_server_requirement'] in guidance
    assert fields['package_command'] in guidance
    assert fields['example_command'] in guidance
    assert fields['factory_command'] in guidance


def test_build_server_kwargs_use_factory_import_path_and_bind_settings() -> None:
    """Verify that the formal entrypoint builds the canonical uvicorn kwargs."""
    kwargs = server.build_server_kwargs(
        settings=ProviderSettings(
            server_host='0.0.0.0',  # noqa: S104 - intentional bind-all case
            server_port=9000,
        )
    )

    assert kwargs == {
        'app': 'copilot_model_provider.app:create_app',
        'factory': True,
        'host': '0.0.0.0',  # noqa: S104 - intentional bind-all case
        'port': 9000,
        'access_log': False,
        'log_config': None,
    }


def test_server_main_runs_uvicorn_with_resolved_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that the package entrypoint starts uvicorn with structlog settings."""
    captured: dict[str, object] = {}

    def fake_from_env(_cls: type[ProviderSettings]) -> ProviderSettings:
        """Return deterministic startup settings for the server entrypoint test."""
        return ProviderSettings(
            server_host='0.0.0.0',  # noqa: S104 - intentional bind-all case
            server_port=8080,
        )

    monkeypatch.setattr(
        server.ProviderSettings,
        'from_env',
        classmethod(fake_from_env),
    )
    monkeypatch.setattr(
        server, 'configure_logging', lambda: captured.setdefault('configured', True)
    )

    def fake_uvicorn_run(**kwargs: object) -> None:
        """Capture the uvicorn kwargs instead of starting the server."""
        captured['kwargs'] = kwargs

    monkeypatch.setattr(server.uvicorn, 'run', fake_uvicorn_run)

    server.main()

    assert captured['configured'] is True
    assert captured['kwargs'] == {
        'app': 'copilot_model_provider.app:create_app',
        'factory': True,
        'host': '0.0.0.0',  # noqa: S104 - intentional bind-all case
        'port': 8080,
        'access_log': False,
        'log_config': None,
    }


def test_module_entrypoint_delegates_to_server_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that ``python -m copilot_model_provider`` delegates to ``server.main``."""
    calls: list[str] = []

    def fake_main() -> None:
        """Record that the module entrypoint delegated to the server function."""
        calls.append('called')

    monkeypatch.setattr(server, 'main', fake_main)

    runpy.run_module('copilot_model_provider.__main__', run_name='__main__')

    assert calls == ['called']
