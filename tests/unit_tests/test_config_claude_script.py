"""Unit tests for the Python Claude configuration orchestration script."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from scripts.config_claude import (
    ConfigClaudeError,
    ConfigClaudeOptions,
    build_claude_env_overrides,
    parse_args,
    run_config_claude,
    select_default_claude_model,
    update_claude_settings_payload,
    update_claude_settings_text,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_run_config_claude_updates_settings_and_creates_backup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify the happy path rewrites settings.json and preserves a backup."""
    claude_dir = tmp_path / '.claude'
    claude_dir.mkdir()
    settings_path = claude_dir / 'settings.json'
    original_settings = (
        json.dumps(
            {
                'permissions': {'mode': 'default'},
                'env': {
                    'KEEP_ME': '1',
                    'ANTHROPIC_API_KEY': 'stale-key',
                },
            },
            indent=2,
        )
        + '\n'
    )
    settings_path.write_text(original_settings, encoding='utf-8')

    restart_calls: list[tuple[str, str, int, int, str]] = []
    health_checks: list[str] = []

    def _ignore_commands(_commands: tuple[str, ...]) -> None:
        """Ignore command checks during unit tests."""

    def _ignore_auth() -> None:
        """Ignore GitHub auth checks during unit tests."""

    def _resolve_token() -> str:
        """Return a deterministic token for unit tests."""
        return 'github-token'

    def _inspect_container(**_: object) -> None:
        """Report that no reusable container exists for the happy-path test."""
        return

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
        """Return visible model ids used by the happy-path test."""
        return ['gpt-5.4', 'claude-haiku-3.5', 'claude-sonnet-4.6']

    monkeypatch.setattr(
        'scripts.config_claude.ensure_required_commands', _ignore_commands
    )
    monkeypatch.setattr('scripts.config_claude.ensure_gh_authenticated', _ignore_auth)
    monkeypatch.setattr('scripts.config_claude.resolve_github_token', _resolve_token)
    monkeypatch.setattr('scripts.config_codex.inspect_container', _inspect_container)
    monkeypatch.setattr('scripts.config_codex.restart_container', _restart)
    monkeypatch.setattr('scripts.config_claude.wait_for_health', _wait)
    monkeypatch.setattr(
        'scripts.config_claude.fetch_visible_anthropic_model_ids', _visible_models
    )

    result = run_config_claude(
        ConfigClaudeOptions(
            port=28080,
            image='copilot-model-provider:local',
        ),
        home_directory=tmp_path,
    )

    payload = json.loads(settings_path.read_text(encoding='utf-8'))
    backup_files = list((claude_dir / 'backups').glob('settings.json.*.bak'))

    assert result.base_url == 'http://127.0.0.1:28080/anthropic'
    assert result.discovery_base_url == 'http://127.0.0.1:28080/anthropic/v1'
    assert result.container_name == 'copilot-model-provider'
    assert result.model == 'claude-sonnet-4.6'
    assert result.settings_path == str(settings_path)
    assert restart_calls == [
        (
            'copilot-model-provider',
            'copilot-model-provider:local',
            28080,
            8000,
            'github-token',
        ),
    ]
    assert health_checks == ['http://127.0.0.1:28080/_internal/health']
    assert payload['permissions'] == {'mode': 'default'}
    assert payload['env']['KEEP_ME'] == '1'
    assert payload['env']['ANTHROPIC_BASE_URL'] == 'http://127.0.0.1:28080/anthropic'
    assert payload['env']['ANTHROPIC_AUTH_TOKEN'] == 'github-token'  # noqa: S105 - deterministic test token
    assert payload['env']['ANTHROPIC_MODEL'] == 'claude-sonnet-4.6'
    assert payload['env']['ANTHROPIC_DEFAULT_SONNET_MODEL'] == 'claude-sonnet-4.6'
    assert payload['env']['ANTHROPIC_DEFAULT_HAIKU_MODEL'] == 'claude-haiku-3.5'
    assert 'ANTHROPIC_API_KEY' not in payload['env']
    assert len(backup_files) == 1
    assert backup_files[0].read_text(encoding='utf-8') == original_settings


def test_run_config_claude_reuses_matching_running_container(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify Claude setup reuses a compatible running provider container."""
    claude_dir = tmp_path / '.claude'
    claude_dir.mkdir()
    settings_path = claude_dir / 'settings.json'
    settings_path.write_text('{\n}\n', encoding='utf-8')

    restart_calls: list[tuple[str, str, int, int, str]] = []
    health_checks: list[str] = []

    def _ignore_commands(_commands: tuple[str, ...]) -> None:
        """Ignore command checks during unit tests."""

    def _ignore_auth() -> None:
        """Ignore GitHub auth checks during unit tests."""

    def _resolve_token() -> str:
        """Return a deterministic token for unit tests."""
        return 'github-token'

    def _inspect_container(**_: object) -> object:
        """Return a running container that matches the requested config."""
        from scripts.config_codex import InspectedContainer

        return InspectedContainer(
            image='copilot-model-provider:local',
            running=True,
            published_port=28080,
        )

    def _restart(
        *,
        container_name: str,
        image: str,
        host_port: int,
        container_port: int,
        github_token: str,
    ) -> None:
        """Record unexpected restart requests during the reuse-path test."""
        restart_calls.append(
            (container_name, image, host_port, container_port, github_token),
        )

    def _wait(url: str) -> None:
        """Capture the health URL instead of polling a live service."""
        health_checks.append(url)

    def _visible_models(_base_url: str) -> list[str]:
        """Return visible model ids used by the reuse-path test."""
        return ['claude-sonnet-4.6']

    monkeypatch.setattr(
        'scripts.config_claude.ensure_required_commands', _ignore_commands
    )
    monkeypatch.setattr('scripts.config_claude.ensure_gh_authenticated', _ignore_auth)
    monkeypatch.setattr('scripts.config_claude.resolve_github_token', _resolve_token)
    monkeypatch.setattr('scripts.config_codex.inspect_container', _inspect_container)
    monkeypatch.setattr('scripts.config_codex.restart_container', _restart)
    monkeypatch.setattr('scripts.config_claude.wait_for_health', _wait)
    monkeypatch.setattr(
        'scripts.config_claude.fetch_visible_anthropic_model_ids', _visible_models
    )

    result = run_config_claude(
        ConfigClaudeOptions(
            port=28080,
            image='copilot-model-provider:local',
        ),
        home_directory=tmp_path,
    )

    payload = json.loads(settings_path.read_text(encoding='utf-8'))
    assert result.model == 'claude-sonnet-4.6'
    assert payload['env']['ANTHROPIC_MODEL'] == 'claude-sonnet-4.6'
    assert restart_calls == []
    assert health_checks == ['http://127.0.0.1:28080/_internal/health']


def test_run_config_claude_restarts_mismatched_container(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify Claude setup restarts a container whose config no longer matches."""
    claude_dir = tmp_path / '.claude'
    claude_dir.mkdir()
    settings_path = claude_dir / 'settings.json'
    settings_path.write_text('{\n}\n', encoding='utf-8')

    restart_calls: list[tuple[str, str, int, int, str]] = []

    def _ignore_commands(_commands: tuple[str, ...]) -> None:
        """Ignore command checks during unit tests."""

    def _ignore_auth() -> None:
        """Ignore GitHub auth checks during unit tests."""

    def _resolve_token() -> str:
        """Return a deterministic token for unit tests."""
        return 'github-token'

    def _inspect_container(**_: object) -> object:
        """Return a running container whose published port mismatches the request."""
        from scripts.config_codex import InspectedContainer

        return InspectedContainer(
            image='copilot-model-provider:local',
            running=True,
            published_port=9000,
        )

    def _restart(
        *,
        container_name: str,
        image: str,
        host_port: int,
        container_port: int,
        github_token: str,
    ) -> None:
        """Capture the restart request triggered by the mismatch."""
        restart_calls.append(
            (container_name, image, host_port, container_port, github_token),
        )

    def _wait(_url: str) -> None:
        """Skip health polling during the mismatch-path test."""

    def _visible_models(_base_url: str) -> list[str]:
        """Return visible model ids used by the mismatch-path test."""
        return ['claude-sonnet-4.6']

    monkeypatch.setattr(
        'scripts.config_claude.ensure_required_commands', _ignore_commands
    )
    monkeypatch.setattr('scripts.config_claude.ensure_gh_authenticated', _ignore_auth)
    monkeypatch.setattr('scripts.config_claude.resolve_github_token', _resolve_token)
    monkeypatch.setattr('scripts.config_codex.inspect_container', _inspect_container)
    monkeypatch.setattr('scripts.config_codex.restart_container', _restart)
    monkeypatch.setattr('scripts.config_claude.wait_for_health', _wait)
    monkeypatch.setattr(
        'scripts.config_claude.fetch_visible_anthropic_model_ids', _visible_models
    )

    run_config_claude(
        ConfigClaudeOptions(
            port=8000,
            image='copilot-model-provider:local',
        ),
        home_directory=tmp_path,
    )

    assert restart_calls == [
        (
            'copilot-model-provider',
            'copilot-model-provider:local',
            8000,
            8000,
            'github-token',
        ),
    ]


def test_run_config_claude_validates_explicit_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify that an explicit Claude model is accepted when it is visible."""

    def _ignore_commands(_commands: tuple[str, ...]) -> None:
        """Ignore command checks during unit tests."""

    def _ignore_auth() -> None:
        """Ignore GitHub auth checks during unit tests."""

    def _resolve_token() -> str:
        """Return a deterministic token for unit tests."""
        return 'github-token'

    def _inspect_container(**_: object) -> None:
        """Report that no reusable container exists for the test."""

    def _restart(**_: object) -> None:
        """Ignore Docker restarts during the test."""

    def _wait(_url: str) -> None:
        """Skip health polling during the test."""

    def _visible_models(_base_url: str) -> list[str]:
        """Return visible models that include the explicit Claude id."""
        return ['claude-opus-4.1', 'claude-sonnet-4.6']

    monkeypatch.setattr(
        'scripts.config_claude.ensure_required_commands', _ignore_commands
    )
    monkeypatch.setattr('scripts.config_claude.ensure_gh_authenticated', _ignore_auth)
    monkeypatch.setattr('scripts.config_claude.resolve_github_token', _resolve_token)
    monkeypatch.setattr('scripts.config_codex.inspect_container', _inspect_container)
    monkeypatch.setattr('scripts.config_codex.restart_container', _restart)
    monkeypatch.setattr('scripts.config_claude.wait_for_health', _wait)
    monkeypatch.setattr(
        'scripts.config_claude.fetch_visible_anthropic_model_ids', _visible_models
    )

    result = run_config_claude(
        ConfigClaudeOptions(
            port=8000,
            image='copilot-model-provider:local',
            model='claude-opus-4.1',
        ),
        home_directory=tmp_path,
    )

    payload = json.loads(
        (tmp_path / '.claude' / 'settings.json').read_text(encoding='utf-8')
    )
    assert result.model == 'claude-opus-4.1'
    assert payload['env']['ANTHROPIC_MODEL'] == 'claude-opus-4.1'
    assert payload['env']['ANTHROPIC_DEFAULT_OPUS_MODEL'] == 'claude-opus-4.1'


def test_run_config_claude_rejects_missing_visible_claude_models(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify the script fails when the provider exposes no Claude-family models."""

    def _ignore_commands(_commands: tuple[str, ...]) -> None:
        """Ignore command checks during unit tests."""

    def _ignore_auth() -> None:
        """Ignore GitHub auth checks during unit tests."""

    def _resolve_token() -> str:
        """Return a deterministic token for unit tests."""
        return 'github-token'

    def _inspect_container(**_: object) -> None:
        """Report that no reusable container exists for the negative-path test."""

    def _restart(**_: object) -> None:
        """Ignore Docker restarts during the negative-path test."""

    def _wait(_url: str) -> None:
        """Skip health polling during the negative-path test."""

    def _visible_models(_base_url: str) -> list[str]:
        """Return a model list that intentionally excludes Claude ids."""
        return ['gpt-5.4', 'o3']

    monkeypatch.setattr(
        'scripts.config_claude.ensure_required_commands', _ignore_commands
    )
    monkeypatch.setattr('scripts.config_claude.ensure_gh_authenticated', _ignore_auth)
    monkeypatch.setattr('scripts.config_claude.resolve_github_token', _resolve_token)
    monkeypatch.setattr('scripts.config_codex.inspect_container', _inspect_container)
    monkeypatch.setattr('scripts.config_codex.restart_container', _restart)
    monkeypatch.setattr('scripts.config_claude.wait_for_health', _wait)
    monkeypatch.setattr(
        'scripts.config_claude.fetch_visible_anthropic_model_ids', _visible_models
    )

    with pytest.raises(
        ConfigClaudeError, match='Unable to choose a Claude-family model'
    ):
        run_config_claude(
            ConfigClaudeOptions(
                port=8000,
                image='copilot-model-provider:local',
            ),
            home_directory=tmp_path,
        )


def test_parse_args_release_channel_uses_published_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify release-channel CLI parsing resolves the published GHCR image."""
    monkeypatch.delenv('CLAUDE_PROVIDER_IMAGE', raising=False)
    monkeypatch.delenv('CLAUDE_PROVIDER_CHANNEL', raising=False)
    monkeypatch.delenv('CLAUDE_PROVIDER_VERSION', raising=False)

    options = parse_args(['--channel', 'release', '--version', 'v0.1.0'])

    assert options.image == 'ghcr.io/lachimere/copilot-model-provider:v0.1.0'
    assert options.image_channel == 'release'
    assert options.release_version == 'v0.1.0'


def test_update_claude_settings_text_rejects_invalid_existing_json() -> None:
    """Verify malformed Claude settings fail fast instead of being rewritten blindly."""
    with pytest.raises(ConfigClaudeError, match='Invalid existing Claude settings'):
        update_claude_settings_text(
            '{invalid json}',
            base_url='http://127.0.0.1:8000/anthropic',
            github_token='github-token',  # noqa: S106 - deterministic test token
            model='claude-sonnet-4.6',
            visible_models=['claude-sonnet-4.6'],
        )


def test_update_claude_settings_payload_preserves_unrelated_fields() -> None:
    """Verify unrelated root keys and env values survive the managed update."""
    updated = update_claude_settings_payload(
        settings_payload={
            'permissions': {'mode': 'acceptEdits'},
            'env': {
                'KEEP_ME': '1',
                'ANTHROPIC_API_KEY': 'stale-key',
            },
        },
        base_url='http://127.0.0.1:8000/anthropic',
        github_token='github-token',  # noqa: S106 - deterministic test token
        model='claude-sonnet-4.6',
        visible_models=['claude-sonnet-4.6', 'claude-haiku-3.5'],
    )

    assert updated['permissions'] == {'mode': 'acceptEdits'}
    assert updated['env'] == {
        'KEEP_ME': '1',
        'ANTHROPIC_BASE_URL': 'http://127.0.0.1:8000/anthropic',
        'ANTHROPIC_AUTH_TOKEN': 'github-token',
        'ANTHROPIC_MODEL': 'claude-sonnet-4.6',
        'ANTHROPIC_DEFAULT_SONNET_MODEL': 'claude-sonnet-4.6',
        'ANTHROPIC_DEFAULT_HAIKU_MODEL': 'claude-haiku-3.5',
    }


def test_build_claude_env_overrides_includes_tier_defaults() -> None:
    """Verify tier-specific defaults are emitted when matching models are visible."""
    overrides = build_claude_env_overrides(
        base_url='http://127.0.0.1:8000/anthropic',
        github_token='github-token',  # noqa: S106 - deterministic test token
        model='claude-sonnet-4.6',
        visible_models=['claude-sonnet-4.6', 'claude-haiku-3.5', 'claude-opus-4.1'],
    )

    assert overrides == {
        'ANTHROPIC_BASE_URL': 'http://127.0.0.1:8000/anthropic',
        'ANTHROPIC_AUTH_TOKEN': 'github-token',
        'ANTHROPIC_MODEL': 'claude-sonnet-4.6',
        'ANTHROPIC_DEFAULT_OPUS_MODEL': 'claude-opus-4.1',
        'ANTHROPIC_DEFAULT_SONNET_MODEL': 'claude-sonnet-4.6',
        'ANTHROPIC_DEFAULT_HAIKU_MODEL': 'claude-haiku-3.5',
    }


def test_select_default_claude_model_prefers_sonnet() -> None:
    """Verify that Sonnet outranks other visible Claude-family models."""
    assert (
        select_default_claude_model(
            visible_models=['claude-haiku-3.5', 'claude-sonnet-4.6', 'claude-opus-4.1']
        )
        == 'claude-sonnet-4.6'
    )
