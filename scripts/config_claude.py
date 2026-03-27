#!/usr/bin/env python3
"""Configure Claude Code to use a local copilot-model-provider container."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

try:
    from scripts.config_codex import (
        DEFAULT_CONTAINER_NAME,
        DEFAULT_CONTAINER_PORT,
        DEFAULT_IMAGE,
        DEFAULT_IMAGE_CHANNEL,
        DEFAULT_PORT,
        DEFAULT_RELEASE_VERSION,
        RELEASE_IMAGE_REPOSITORY,
        ConfigCodexError,
        _parse_port,
        ensure_gh_authenticated,
        ensure_required_commands,
        fetch_visible_anthropic_model_ids,
        resolve_github_token,
        resolve_provider_image,
        restart_container,
        wait_for_health,
    )
except ModuleNotFoundError:
    from config_codex import (  # type: ignore[reportMissingImports]
        DEFAULT_CONTAINER_NAME,
        DEFAULT_CONTAINER_PORT,
        DEFAULT_IMAGE,
        DEFAULT_IMAGE_CHANNEL,
        DEFAULT_PORT,
        DEFAULT_RELEASE_VERSION,
        RELEASE_IMAGE_REPOSITORY,
        ConfigCodexError,
        _parse_port,
        ensure_gh_authenticated,
        ensure_required_commands,
        fetch_visible_anthropic_model_ids,
        resolve_github_token,
        resolve_provider_image,
        restart_container,
        wait_for_health,
    )

DEFAULT_MODEL_ENV_VAR = 'CLAUDE_PROVIDER_MODEL'
DEFAULT_PORT_ENV_VAR = 'CLAUDE_PROVIDER_PORT'
DEFAULT_IMAGE_ENV_VAR = 'CLAUDE_PROVIDER_IMAGE'
DEFAULT_CHANNEL_ENV_VAR = 'CLAUDE_PROVIDER_CHANNEL'
DEFAULT_VERSION_ENV_VAR = 'CLAUDE_PROVIDER_VERSION'
DEFAULT_CLAUDE_CONFIG_DIR_ENV_VAR = 'CLAUDE_CONFIG_DIR'
DEFAULT_SETTINGS_FILE_NAME = 'settings.json'
DEFAULT_BACKUP_DIR_NAME = 'backups'


class ConfigClaudeError(RuntimeError):
    """Raised when local Claude/provider configuration cannot be completed."""


@dataclass(frozen=True)
class ConfigClaudeOptions:
    """Normalized CLI options for configuring Claude against the local provider.

    Attributes:
        port: Host port exposed by the local provider container.
        image: Docker image tag to run for the provider container.
        model: Optional Claude-family model id to force for the configured
            default session.
        image_channel: Image selection mode used when ``image`` is not explicitly
            supplied.
        release_version: Published image version used when ``image_channel`` is
            ``release`` and ``image`` is not explicitly supplied.
        container_port: Internal container port exposed by the provider image.

    """

    port: int
    image: str
    model: str | None = None
    image_channel: Literal['local', 'release'] = DEFAULT_IMAGE_CHANNEL
    release_version: str = DEFAULT_RELEASE_VERSION
    container_port: int = DEFAULT_CONTAINER_PORT


@dataclass(frozen=True)
class ConfigClaudeResult:
    """Summary of the local Claude configuration that was applied.

    Attributes:
        base_url: Anthropic-compatible provider base URL written to settings.
        discovery_base_url: Anthropic-compatible provider base URL used to validate
            visible models before writing settings.
        container_name: Docker container name started for the local provider.
        image: Docker image tag used for the running container.
        model: Claude-family model id written as the default model.
        settings_path: Settings file updated for persistent Claude startup.
        backup_path: Backup path created for the prior settings contents, or a
            note that no prior settings file existed.

    """

    base_url: str
    discovery_base_url: str
    container_name: str
    image: str
    model: str
    settings_path: str
    backup_path: str


def parse_args(argv: list[str] | None = None) -> ConfigClaudeOptions:
    """Parse CLI arguments into validated ``ConfigClaudeOptions`` values."""
    parser = argparse.ArgumentParser(
        description=(
            'Configure Claude Code to use a locally deployed '
            'copilot-model-provider container.'
        ),
    )
    parser.add_argument(
        '--port',
        type=_parse_port,
        default=_parse_port(os.environ.get(DEFAULT_PORT_ENV_VAR, str(DEFAULT_PORT))),
        help=f'Host port that maps to the service container (default: {DEFAULT_PORT})',
    )
    parser.add_argument(
        '--channel',
        choices=('local', 'release'),
        default=os.environ.get(DEFAULT_CHANNEL_ENV_VAR, DEFAULT_IMAGE_CHANNEL),
        help=(
            'Image source to use when --image is not provided: '
            f'"local" -> {DEFAULT_IMAGE}; '
            f'"release" -> {RELEASE_IMAGE_REPOSITORY}:<version> '
            f'(default: {DEFAULT_IMAGE_CHANNEL})'
        ),
    )
    parser.add_argument(
        '--version',
        default=os.environ.get(DEFAULT_VERSION_ENV_VAR, DEFAULT_RELEASE_VERSION),
        help=(
            'Published image version to use together with --channel release '
            f'(default: {DEFAULT_RELEASE_VERSION})'
        ),
    )
    parser.add_argument(
        '--image',
        default=os.environ.get(DEFAULT_IMAGE_ENV_VAR),
        help=(
            'Explicit Docker image name to run. When omitted, the script derives '
            'the image from --channel and --version.'
        ),
    )
    parser.add_argument(
        '--model',
        default=os.environ.get(DEFAULT_MODEL_ENV_VAR),
        help=(
            'Claude-family model ID to persist in Claude settings. When omitted, '
            'the script auto-selects the best visible Claude model.'
        ),
    )
    args = parser.parse_args(argv)
    return ConfigClaudeOptions(
        port=args.port,
        image=resolve_provider_image(
            explicit_image=args.image,
            image_channel=cast("Literal['local', 'release']", args.channel),
            release_version=args.version,
        ),
        model=args.model,
        image_channel=cast("Literal['local', 'release']", args.channel),
        release_version=args.version,
    )


def run_config_claude(
    options: ConfigClaudeOptions,
    *,
    home_directory: Path | None = None,
) -> ConfigClaudeResult:
    """Run the full local Claude configuration flow.

    The flow validates prerequisites, resolves the user's GitHub token via
        ``gh``, restarts the local provider container, validates the visible
        Claude-family models from ``/anthropic/v1/models``, backs up Claude's user
    ``settings.json``, and rewrites the persistent env block so future
    ``claude`` invocations route through the local provider.

    Args:
        options: Validated CLI options for the Claude configuration workflow.
        home_directory: Optional home-directory override for tests.

    Returns:
        A ``ConfigClaudeResult`` describing the persistent configuration that was
        written for Claude.

    Raises:
        ConfigClaudeError: If prerequisites, provider startup, model discovery,
            or settings rewrite fails.

    """
    try:
        ensure_required_commands(('docker', 'gh', 'claude'))
        ensure_gh_authenticated()
        github_token = resolve_github_token()

        base_url = f'http://127.0.0.1:{options.port}/anthropic'
        discovery_base_url = f'http://127.0.0.1:{options.port}/anthropic/v1'
        container_name = DEFAULT_CONTAINER_NAME
        config_dir = resolve_claude_config_dir(home_directory=home_directory)
        settings_path = config_dir / DEFAULT_SETTINGS_FILE_NAME
        backup_dir = config_dir / DEFAULT_BACKUP_DIR_NAME

        restart_container(
            container_name=container_name,
            image=options.image,
            host_port=options.port,
            container_port=options.container_port,
            github_token=github_token,
        )
        wait_for_health(f'http://127.0.0.1:{options.port}/_internal/health')

        visible_models = fetch_visible_anthropic_model_ids(discovery_base_url)
        selected_model = resolve_claude_model(
            preferred_model=options.model,
            visible_models=visible_models,
        )
        backup_path = backup_claude_settings(settings_path, backup_dir)
        write_updated_claude_settings(
            settings_path,
            base_url=base_url,
            github_token=github_token,
            model=selected_model,
            visible_models=visible_models,
        )
    except ConfigCodexError as error:
        raise ConfigClaudeError(str(error)) from error

    return ConfigClaudeResult(
        base_url=base_url,
        discovery_base_url=discovery_base_url,
        container_name=container_name,
        image=options.image,
        model=selected_model,
        settings_path=str(settings_path),
        backup_path=backup_path,
    )


def resolve_claude_config_dir(*, home_directory: Path | None = None) -> Path:
    """Resolve the Claude config directory for the current invocation.

    Args:
        home_directory: Optional home-directory override used by tests.

    Returns:
        The effective Claude config directory, preferring ``CLAUDE_CONFIG_DIR``
        when present and otherwise falling back to ``<home>/.claude``.

    """
    explicit_config_dir = os.environ.get(DEFAULT_CLAUDE_CONFIG_DIR_ENV_VAR)
    if explicit_config_dir:
        return Path(explicit_config_dir).expanduser()
    return (home_directory or Path.home()) / '.claude'


def backup_claude_settings(settings_path: Path, backup_dir: Path) -> str:
    """Create or initialize Claude settings and return the backup path display.

    Args:
        settings_path: Filesystem path to Claude's ``settings.json`` file.
        backup_dir: Directory where settings backups should be stored.

    Returns:
        The backup path when a prior settings file existed, otherwise a note that
        no prior settings file was present.

    """
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    backup_dir.mkdir(parents=True, exist_ok=True)

    if settings_path.exists():
        timestamp = datetime.now(UTC).strftime('%Y%m%d-%H%M%S')
        backup_path = backup_dir / f'settings.json.{timestamp}.bak'
        shutil.copy2(settings_path, backup_path)
        return str(backup_path)

    settings_path.write_text('{\n}\n', encoding='utf-8')
    return '(none; settings did not exist)'


def write_updated_claude_settings(
    settings_path: Path,
    *,
    base_url: str,
    github_token: str,
    model: str,
    visible_models: list[str],
) -> None:
    """Load, update, validate, and rewrite Claude settings in place.

    Args:
        settings_path: Filesystem path to Claude's ``settings.json`` file.
        base_url: Anthropic-compatible provider base URL to persist.
        github_token: GitHub token to persist as ``ANTHROPIC_AUTH_TOKEN``.
        model: Default Claude-family model to persist.
        visible_models: Live models visible from the provider, used to set tier
            defaults alongside the selected model.

    """
    source = settings_path.read_text(encoding='utf-8')
    updated = update_claude_settings_text(
        source,
        base_url=base_url,
        github_token=github_token,
        model=model,
        visible_models=visible_models,
    )
    settings_path.write_text(updated, encoding='utf-8')


def update_claude_settings_text(
    source: str,
    *,
    base_url: str,
    github_token: str,
    model: str,
    visible_models: list[str],
) -> str:
    """Return updated Claude settings JSON for the local provider integration.

    Args:
        source: Existing ``settings.json`` contents, which may be empty.
        base_url: Anthropic-compatible provider base URL to persist.
        github_token: GitHub token to persist as ``ANTHROPIC_AUTH_TOKEN``.
        model: Default Claude-family model to persist.
        visible_models: Live models visible from the provider, used to derive
            additional per-tier model defaults.

    Returns:
        Pretty-printed JSON text with the provider-related env values updated.

    Raises:
        ConfigClaudeError: If the existing settings are invalid JSON or do not
            have the expected object structure.

    """
    settings_payload = _load_settings_document(
        source, context='existing Claude settings'
    )
    updated_payload = update_claude_settings_payload(
        settings_payload=settings_payload,
        base_url=base_url,
        github_token=github_token,
        model=model,
        visible_models=visible_models,
    )
    return json.dumps(updated_payload, indent=2, sort_keys=True) + '\n'


def update_claude_settings_payload(
    *,
    settings_payload: dict[str, object],
    base_url: str,
    github_token: str,
    model: str,
    visible_models: list[str],
) -> dict[str, object]:
    """Return updated Claude settings payload with provider env overrides.

    Args:
        settings_payload: Parsed ``settings.json`` object.
        base_url: Anthropic-compatible provider base URL to persist.
        github_token: GitHub token to persist as ``ANTHROPIC_AUTH_TOKEN``.
        model: Default Claude-family model to persist.
        visible_models: Live models visible from the provider.

    Returns:
        A new settings payload with the env block updated for local-provider use.

    Raises:
        ConfigClaudeError: If the existing ``env`` field is present but not a
            JSON object.

    """
    updated_payload = dict(settings_payload)
    existing_env = updated_payload.get('env')
    if existing_env is None:
        env_payload: dict[str, object] = {}
    elif isinstance(existing_env, dict):
        typed_existing_env = cast('dict[object, object]', existing_env)
        env_payload = {str(key): value for key, value in typed_existing_env.items()}
    else:
        msg = 'Invalid existing Claude settings: `env` must be a JSON object.'
        raise ConfigClaudeError(msg)

    env_payload.update(
        build_claude_env_overrides(
            base_url=base_url,
            github_token=github_token,
            model=model,
            visible_models=visible_models,
        )
    )
    env_payload.pop('ANTHROPIC_API_KEY', None)
    updated_payload['env'] = env_payload
    return updated_payload


def build_claude_env_overrides(
    *,
    base_url: str,
    github_token: str,
    model: str,
    visible_models: list[str],
) -> dict[str, object]:
    """Build the Claude env overrides that should persist in settings.

    Args:
        base_url: Anthropic-compatible provider base URL to persist.
        github_token: GitHub token to persist as ``ANTHROPIC_AUTH_TOKEN``.
        model: Default Claude-family model to persist.
        visible_models: Live models visible from the provider.

    Returns:
        A JSON-like mapping of Claude env keys to persisted values.

    """
    env_overrides: dict[str, object] = {
        'ANTHROPIC_BASE_URL': base_url,
        'ANTHROPIC_AUTH_TOKEN': github_token,
        'ANTHROPIC_MODEL': model,
    }

    tier_defaults = {
        'ANTHROPIC_DEFAULT_OPUS_MODEL': find_preferred_model_for_prefix(
            visible_models=visible_models,
            prefix='claude-opus',
        ),
        'ANTHROPIC_DEFAULT_SONNET_MODEL': find_preferred_model_for_prefix(
            visible_models=visible_models,
            prefix='claude-sonnet',
        ),
        'ANTHROPIC_DEFAULT_HAIKU_MODEL': find_preferred_model_for_prefix(
            visible_models=visible_models,
            prefix='claude-haiku',
        ),
    }
    env_overrides.update(
        {key: value for key, value in tier_defaults.items() if value is not None}
    )

    return env_overrides


def resolve_claude_model(
    *,
    preferred_model: str | None,
    visible_models: list[str],
) -> str:
    """Resolve the Claude model that should be persisted in settings.

    Args:
        preferred_model: Optional user-specified Claude model identifier.
        visible_models: Live model identifiers visible from the running provider.

    Returns:
        The explicit model when it is visible, otherwise the best visible
        Claude-family model selected from the live catalog.

    Raises:
        ConfigClaudeError: If no visible Claude-family model can be selected.

    """
    if preferred_model is not None:
        if preferred_model in visible_models:
            return preferred_model
        available_models = ', '.join(visible_models) if visible_models else '(none)'
        msg = (
            f'Requested model {preferred_model!r} is not visible from the running service.\n'
            f'Available models: {available_models}'
        )
        raise ConfigClaudeError(msg)

    selected_model = select_default_claude_model(visible_models=visible_models)
    if selected_model is None:
        available_models = ', '.join(visible_models) if visible_models else '(none)'
        msg = (
            'Unable to choose a Claude-family model from the running service.\n'
            f'Available models: {available_models}'
        )
        raise ConfigClaudeError(msg)
    return selected_model


def select_default_claude_model(*, visible_models: list[str]) -> str | None:
    """Select the preferred visible Claude-family model from the live catalog.

    The local provider may surface several Claude-family variants. This helper
    prefers Sonnet first, then Opus, then Haiku, and finally any remaining
    identifier that begins with ``claude-``.

    Args:
        visible_models: Live model identifiers visible from the provider.

    Returns:
        The preferred Claude-family model identifier, or ``None`` when none are
        visible.

    """
    model_preferences = ('claude-sonnet', 'claude-opus', 'claude-haiku')
    for prefix in model_preferences:
        preferred_model = find_preferred_model_for_prefix(
            visible_models=visible_models,
            prefix=prefix,
        )
        if preferred_model is not None:
            return preferred_model

    for model_id in visible_models:
        if model_id.startswith('claude-'):
            return model_id

    return None


def find_preferred_model_for_prefix(
    *,
    visible_models: list[str],
    prefix: str,
) -> str | None:
    """Return the first visible model that matches the requested prefix.

    Args:
        visible_models: Live model identifiers visible from the provider.
        prefix: Claude-family prefix to search for.

    Returns:
        The first matching model identifier, or ``None`` when none match.

    """
    for model_id in visible_models:
        if model_id.startswith(prefix):
            return model_id
    return None


def _load_settings_document(source: str, *, context: str) -> dict[str, object]:
    """Parse Claude settings JSON and require a top-level object payload.

    Args:
        source: Raw ``settings.json`` contents.
        context: Human-readable context used in validation errors.

    Returns:
        The parsed top-level JSON object.

    Raises:
        ConfigClaudeError: If the JSON is invalid or does not decode to an
            object.

    """
    normalized_source = source.strip()
    if not normalized_source:
        return {}

    try:
        payload = json.loads(source)
    except json.JSONDecodeError as error:
        msg = f'Invalid {context}: {error}'
        raise ConfigClaudeError(msg) from error

    if isinstance(payload, dict):
        typed_payload = cast('dict[object, object]', payload)
        return {str(key): value for key, value in typed_payload.items()}

    msg = f'Invalid {context}: top-level JSON value must be an object.'
    raise ConfigClaudeError(msg)


def main(argv: list[str] | None = None) -> int:
    """Run the CLI entrypoint and persist Claude's local provider settings."""
    options = parse_args(argv)

    try:
        result = run_config_claude(options)
    except ConfigClaudeError as error:
        print(error, file=sys.stderr)
        return 1

    print(f'Configured Claude to use {result.base_url}')
    print(f'Discovery endpoint: {result.discovery_base_url}/models')
    print(f'Container name: {result.container_name}')
    print(f'Image: {result.image}')
    print(f'Default model: {result.model}')
    print(f'Settings: {result.settings_path}')
    print(f'Backup: {result.backup_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
