"""Unit tests for service entrypoint helpers."""

from __future__ import annotations

import runpy
from typing import TYPE_CHECKING

from copilot_model_provider import server

if TYPE_CHECKING:
    import pytest


def test_build_startup_guidance_describes_service_entrypoint() -> None:
    """Verify that the helper describes the service-first startup model."""
    guidance = server.build_startup_guidance()

    assert 'service package, not an end-user CLI' in guidance
    assert 'Use an installed ASGI server such as uvicorn' in guidance
    assert 'uvicorn copilot_model_provider.app:app' in guidance
    assert 'uvicorn copilot_model_provider.app:create_app --factory' in guidance


def test_build_startup_guidance_fields_match_text_guidance() -> None:
    """Verify that structured guidance fields remain aligned with text output."""
    fields = server.build_startup_guidance_fields()
    guidance = server.build_startup_guidance()

    assert fields['summary'] in guidance
    assert fields['asgi_server_requirement'] in guidance
    assert fields['example_command'] in guidance
    assert fields['factory_command'] in guidance


def test_server_main_prints_service_startup_guidance(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify that the thin service entrypoint logs actionable guidance."""
    server.main()

    captured = capsys.readouterr()
    assert 'service_entrypoint_guidance' in captured.out
    assert 'service package, not an end-user CLI' in captured.out
    assert 'Use an installed ASGI server such as uvicorn' in captured.out
    assert 'uvicorn copilot_model_provider.app:app' in captured.out
    assert 'uvicorn copilot_model_provider.app:create_app --factory' in captured.out


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
