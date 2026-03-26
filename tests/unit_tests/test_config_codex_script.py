"""Unit tests for the Python Codex configuration orchestration script."""

from __future__ import annotations

import tomllib
import urllib.request
from typing import TYPE_CHECKING

import pytest

from scripts.config_codex import (
    ConfigCodexError,
    ConfigCodexOptions,
    _fetch_json_document,
    run_config_codex,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_run_config_codex_updates_config_and_creates_backup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify the happy path rewrites config.toml and preserves a backup."""
    codex_dir = tmp_path / '.codex'
    codex_dir.mkdir()
    config_path = codex_dir / 'config.toml'
    original_config = 'approval_policy = "on-failure"\n'
    config_path.write_text(original_config, encoding='utf-8')

    restart_calls: list[tuple[str, str, int, int, str]] = []
    health_checks: list[str] = []

    def _ignore_commands(_commands: tuple[str, ...]) -> None:
        """Ignore command checks during unit tests."""

    def _ignore_auth() -> None:
        """Ignore GitHub auth checks during unit tests."""

    def _resolve_token() -> str:
        """Return a deterministic token for unit tests."""
        return 'github-token'

    def _restart(
        *,
        container_name: str,
        image: str,
        host_port: int,
        container_port: int,
        github_token: str,
    ) -> None:
        """Capture the restart request instead of calling Docker."""
        restart_calls.append(
            (container_name, image, host_port, container_port, github_token),
        )

    def _wait(url: str) -> None:
        """Capture the health URL instead of polling a live service."""
        health_checks.append(url)

    def _visible_models(_base_url: str) -> list[str]:
        """Return the visible model ids used by the happy-path test."""
        return ['gpt-5.4', 'gpt-5.4-mini']

    monkeypatch.setattr(
        'scripts.config_codex.ensure_required_commands',
        _ignore_commands,
    )
    monkeypatch.setattr(
        'scripts.config_codex.ensure_gh_authenticated',
        _ignore_auth,
    )
    monkeypatch.setattr(
        'scripts.config_codex.resolve_github_token',
        _resolve_token,
    )
    monkeypatch.setattr(
        'scripts.config_codex.restart_container',
        _restart,
    )
    monkeypatch.setattr(
        'scripts.config_codex.wait_for_health',
        _wait,
    )
    monkeypatch.setattr(
        'scripts.config_codex.fetch_visible_model_ids',
        _visible_models,
    )

    result = run_config_codex(
        ConfigCodexOptions(
            port=27070,
            image='copilot-model-provider:local',
            model='gpt-5.4',
        ),
        home_directory=tmp_path,
    )

    payload = tomllib.loads(config_path.read_text(encoding='utf-8'))
    backup_files = list((codex_dir / 'backups').glob('config.toml.*.bak'))

    assert result.base_url == 'http://127.0.0.1:27070/v1'
    assert result.container_name == 'copilot-model-provider-local-27070'
    assert restart_calls == [
        (
            'copilot-model-provider-local-27070',
            'copilot-model-provider:local',
            27070,
            8000,
            'github-token',
        ),
    ]
    assert health_checks == ['http://127.0.0.1:27070/_internal/health']
    assert payload['model'] == 'gpt-5.4'
    assert payload['model_provider'] == 'copilot-model-provider-local'
    assert (
        payload['model_providers']['copilot-model-provider-local']['base_url']
        == 'http://127.0.0.1:27070/v1'
    )
    assert len(backup_files) == 1
    assert backup_files[0].read_text(encoding='utf-8') == original_config


def test_run_config_codex_rejects_model_ids_not_visible_from_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify the script fails before rewriting config when the chosen model is absent."""

    def _ignore_commands(_commands: tuple[str, ...]) -> None:
        """Ignore command checks during unit tests."""

    def _ignore_auth() -> None:
        """Ignore GitHub auth checks during unit tests."""

    def _resolve_token() -> str:
        """Return a deterministic token for unit tests."""
        return 'github-token'

    def _restart(**_: object) -> None:
        """Ignore Docker restarts during the negative-path test."""

    def _wait(_url: str) -> None:
        """Skip health polling during the negative-path test."""

    def _visible_models(_base_url: str) -> list[str]:
        """Return a model list that intentionally excludes the requested id."""
        return ['gpt-4.1']

    monkeypatch.setattr(
        'scripts.config_codex.ensure_required_commands',
        _ignore_commands,
    )
    monkeypatch.setattr(
        'scripts.config_codex.ensure_gh_authenticated',
        _ignore_auth,
    )
    monkeypatch.setattr(
        'scripts.config_codex.resolve_github_token',
        _resolve_token,
    )
    monkeypatch.setattr(
        'scripts.config_codex.restart_container',
        _restart,
    )
    monkeypatch.setattr(
        'scripts.config_codex.wait_for_health',
        _wait,
    )
    monkeypatch.setattr(
        'scripts.config_codex.fetch_visible_model_ids',
        _visible_models,
    )

    with pytest.raises(ConfigCodexError, match='not visible from the running service'):
        run_config_codex(
            ConfigCodexOptions(
                port=8000,
                image='copilot-model-provider:local',
                model='gpt-5.4',
            ),
            home_directory=tmp_path,
        )


def test_fetch_json_document_wraps_connection_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify transient socket resets become user-facing configuration errors."""

    def _raise_connection_reset(*_args: object, **_kwargs: object) -> object:
        """Raise the socket reset seen during early container startup."""
        raise ConnectionResetError(54, 'Connection reset by peer')

    monkeypatch.setattr(urllib.request, 'urlopen', _raise_connection_reset)

    with pytest.raises(ConfigCodexError, match='Unable to fetch'):
        _fetch_json_document('http://127.0.0.1:8000/_internal/health')
