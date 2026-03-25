"""Unit tests for CLI entrypoints."""

from __future__ import annotations

import runpy
from typing import TYPE_CHECKING

from copilot_model_provider import cli

if TYPE_CHECKING:
    import pytest


def test_cli_main_prints_placeholder_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify that the placeholder CLI emits the expected smoke-test message."""
    cli.main()

    captured = capsys.readouterr()
    assert captured.out == 'Hello from copilot-model-provider!\n'


def test_module_entrypoint_delegates_to_cli_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that ``python -m copilot_model_provider`` delegates to ``cli.main``."""
    calls: list[str] = []

    def fake_main() -> None:
        """Record that the module entrypoint delegated to the CLI function."""
        calls.append('called')

    monkeypatch.setattr(cli, 'main', fake_main)

    runpy.run_module('copilot_model_provider.__main__', run_name='__main__')

    assert calls == ['called']
