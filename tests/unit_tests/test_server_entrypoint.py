"""Unit tests for service entrypoint helpers."""

from __future__ import annotations

import runpy

import pytest

from copilot_model_provider import server
from copilot_model_provider.config import ProviderSettings


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


def test_build_server_command_uses_factory_import_path_and_bind_settings() -> None:
    """Verify that the formal entrypoint builds the canonical uvicorn command."""
    command = server.build_server_command(
        settings=ProviderSettings(
            server_host='0.0.0.0',  # noqa: S104 - intentional bind-all case
            server_port=9000,
        )
    )

    assert command == (
        'uvicorn',
        'copilot_model_provider.app:create_app',
        '--factory',
        '--host',
        '0.0.0.0',  # noqa: S104 - intentional bind-all case
        '--port',
        '9000',
    )


def test_server_main_execs_uvicorn_with_resolved_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that the package entrypoint replaces itself with uvicorn."""
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
        server, '_resolve_uvicorn_executable', lambda: '/usr/bin/uvicorn'
    )

    def fake_exec_server_command(
        *,
        executable_path: str,
        command: tuple[str, ...],
    ) -> None:
        """Capture the command instead of replacing the current process."""
        captured['executable_path'] = executable_path
        captured['command'] = command

    monkeypatch.setattr(server, '_exec_server_command', fake_exec_server_command)

    server.main()

    assert captured['executable_path'] == '/usr/bin/uvicorn'
    assert captured['command'] == (
        'uvicorn',
        'copilot_model_provider.app:create_app',
        '--factory',
        '--host',
        '0.0.0.0',  # noqa: S104 - intentional bind-all case
        '--port',
        '8080',
    )


def test_server_main_raises_when_uvicorn_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that startup fails clearly when the ASGI server is unavailable."""

    def fake_which(_name: str) -> None:
        """Report that the requested executable cannot be found on PATH."""

    monkeypatch.setattr(server.shutil, 'which', fake_which)

    with pytest.raises(RuntimeError, match='uvicorn'):
        server._resolve_uvicorn_executable()


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
