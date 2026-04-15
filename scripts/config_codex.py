#!/usr/bin/env python3
"""Configure Codex CLI/App to use a local copilot-model-provider container."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

DEFAULT_PORT = 8000
DEFAULT_IMAGE = 'copilot-model-provider:local'
DEFAULT_IMAGE_CHANNEL = 'local'
DEFAULT_RELEASE_VERSION = 'latest'
RELEASE_IMAGE_REPOSITORY = 'ghcr.io/lachimere/copilot-model-provider'
DEFAULT_PROVIDER_ID = 'copilot-model-provider-local'
DEFAULT_PROVIDER_DISPLAY_NAME = 'GitHub Copilot'
DEFAULT_CONTAINER_NAME = 'copilot-model-provider'
DEFAULT_CONTAINER_PORT = 8000
MAX_PORT = 65535
HEALTH_CHECK_ATTEMPTS = 30
HEALTH_CHECK_DELAY_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 30
TABLE_HEADER_PATTERN = re.compile(r'^\s*(\[\[?)(.+?)(\]\]?)\s*(?:#.*)?$')
ROOT_KEY_PATTERN = re.compile(r'^\s*([A-Za-z0-9_-]+)\s*=')
BARE_KEY_PATTERN = re.compile(r'^[A-Za-z0-9_-]+$')
PROVIDER_TABLE_PREFIX_LENGTH = 2


class ConfigCodexError(RuntimeError):
    """Raised when local Codex/provider configuration cannot be completed."""


@dataclass(frozen=True)
class ConfigCodexOptions:
    """Normalized CLI options for configuring Codex against the local provider.

    Attributes:
        port: Host port exposed by the local provider container.
        image: Docker image tag to run for the provider container.
        image_channel: Image selection mode used when ``image`` is not explicitly
            supplied.
        release_version: Published image version used when ``image_channel`` is
            ``release`` and ``image`` is not explicitly supplied.
        model: Optional Codex model id that should be written into ``config.toml``.
            When omitted, the script auto-selects a preferred visible live model.
        provider_id: Provider identifier stored in the Codex config.
        container_port: Internal container port exposed by the provider image.

    """

    port: int
    image: str
    model: str | None
    image_channel: Literal['local', 'release'] = DEFAULT_IMAGE_CHANNEL
    release_version: str = DEFAULT_RELEASE_VERSION
    provider_id: str = DEFAULT_PROVIDER_ID
    container_port: int = DEFAULT_CONTAINER_PORT


@dataclass(frozen=True)
class ConfigCodexResult:
    """Summary of the local Codex configuration that was applied.

    Attributes:
        base_url: OpenAI-compatible provider base URL written into Codex config.
        container_name: Docker container name started for the local provider.
        image: Docker image tag used for the running container.
        model: Codex model id written into the config.
        backup_path: Backup path created for the prior ``config.toml`` contents,
            or a note that no prior config existed.

    """

    base_url: str
    container_name: str
    image: str
    model: str
    backup_path: str


@dataclass(frozen=True)
class InspectedContainer:
    """Normalized Docker inspect data for one local provider container.

    Attributes:
        image: Docker image reference used by the inspected container.
        running: Whether Docker currently reports the container as running.
        published_port: Host port currently published for the expected service
            container port, or ``None`` when that port is not published.

    """

    image: str
    running: bool
    published_port: int | None


def parse_args(argv: list[str] | None = None) -> ConfigCodexOptions:
    """Parse CLI arguments into validated ``ConfigCodexOptions`` values."""
    parser = argparse.ArgumentParser(
        description=(
            'Configure Codex CLI/App to use a locally deployed '
            'copilot-model-provider container.'
        ),
    )
    parser.add_argument(
        '--port',
        type=_parse_port,
        default=_parse_port(os.environ.get('CODEX_PROVIDER_PORT', str(DEFAULT_PORT))),
        help=f'Host port that maps to the service container (default: {DEFAULT_PORT})',
    )
    parser.add_argument(
        '--channel',
        choices=('local', 'release'),
        default=os.environ.get('CODEX_PROVIDER_CHANNEL', DEFAULT_IMAGE_CHANNEL),
        help=(
            'Image source to use when --image is not provided: '
            f'"local" -> {DEFAULT_IMAGE}; '
            f'"release" -> {RELEASE_IMAGE_REPOSITORY}:<version> '
            f'(default: {DEFAULT_IMAGE_CHANNEL})'
        ),
    )
    parser.add_argument(
        '--version',
        default=os.environ.get('CODEX_PROVIDER_VERSION', DEFAULT_RELEASE_VERSION),
        help=(
            'Published image version to use together with --channel release '
            f'(default: {DEFAULT_RELEASE_VERSION})'
        ),
    )
    parser.add_argument(
        '--image',
        default=os.environ.get('CODEX_PROVIDER_IMAGE'),
        help=(
            'Explicit Docker image name to run. When omitted, the script derives '
            'the image from --channel and --version.'
        ),
    )
    parser.add_argument(
        '--model',
        default=os.environ.get('CODEX_PROVIDER_MODEL'),
        help=(
            'Codex model ID to select. When omitted, the script auto-selects '
            'a preferred visible live model.'
        ),
    )
    args = parser.parse_args(argv)
    return ConfigCodexOptions(
        port=args.port,
        image=resolve_provider_image(
            explicit_image=args.image,
            image_channel=args.channel,
            release_version=args.version,
        ),
        image_channel=cast("Literal['local', 'release']", args.channel),
        release_version=args.version,
        model=args.model,
    )


def resolve_provider_image(
    *,
    explicit_image: str | None,
    image_channel: Literal['local', 'release'],
    release_version: str,
) -> str:
    """Resolve the Docker image reference used for one configuration run.

    Args:
        explicit_image: Optional explicit image reference supplied by the user.
        image_channel: Image source to use when no explicit image is provided.
        release_version: Published image tag used for the release channel.

    Returns:
        The Docker image reference that should be started locally.

    Raises:
        ConfigCodexError: If the explicit image or release version is empty after
            trimming.

    """
    if explicit_image is not None:
        normalized_image = explicit_image.strip()
        if normalized_image:
            return normalized_image
        msg = 'Explicit image override cannot be empty.'
        raise ConfigCodexError(msg)

    if image_channel == 'local':
        return DEFAULT_IMAGE

    normalized_version = release_version.strip()
    if not normalized_version:
        msg = 'Release image version cannot be empty when --channel release is used.'
        raise ConfigCodexError(msg)
    return f'{RELEASE_IMAGE_REPOSITORY}:{normalized_version}'


def run_config_codex(
    options: ConfigCodexOptions,
    *,
    home_directory: Path | None = None,
) -> ConfigCodexResult:
    """Run the full local Codex configuration flow.

    The flow validates prerequisites, resolves the user's GitHub token via
    ``gh``, reuses a compatible running local provider container when possible
    (otherwise restarting it), validates that the requested model is visible
    from ``/openai/v1/models``, backs up ``~/.codex/config.toml``, and rewrites
    the Codex config to point at the local provider.
    """
    ensure_required_commands(('docker', 'gh'))
    ensure_gh_authenticated()
    github_token = resolve_github_token()

    base_url = f'http://127.0.0.1:{options.port}/openai/v1'
    container_name = DEFAULT_CONTAINER_NAME
    codex_dir = (home_directory or Path.home()) / '.codex'
    config_path = codex_dir / 'config.toml'
    backup_dir = codex_dir / 'backups'
    backup_path = backup_codex_config(config_path, backup_dir)

    ensure_provider_container(
        container_name=container_name,
        image=options.image,
        host_port=options.port,
        container_port=options.container_port,
        github_token=github_token,
    )
    wait_for_health(f'http://127.0.0.1:{options.port}/_internal/health')

    visible_models = fetch_visible_model_ids(base_url)
    selected_model = resolve_codex_model(
        preferred_model=options.model,
        visible_models=visible_models,
    )

    write_updated_codex_config(
        config_path,
        model=selected_model,
        provider_id=options.provider_id,
        base_url=base_url,
    )
    return ConfigCodexResult(
        base_url=base_url,
        container_name=container_name,
        image=options.image,
        model=selected_model,
        backup_path=backup_path,
    )


def ensure_required_commands(commands: tuple[str, ...]) -> None:
    """Fail early when required external commands are missing from ``PATH``."""
    for command in commands:
        if shutil.which(command) is None:
            msg = f'Required command not found: {command}'
            raise ConfigCodexError(msg)


def ensure_gh_authenticated() -> None:
    """Ensure the user has an authenticated GitHub CLI session.

    The local provider container relies on the token returned by
    ``gh auth token``. When ``gh`` is not currently authenticated, this helper
    launches an interactive browser-based OAuth login flow and verifies that the
    login completed before returning.

    Raises:
        ConfigCodexError: If ``gh`` login fails or authentication is still
            unavailable after the login flow completes.

    """
    if _gh_auth_status_is_authenticated():
        return

    print(
        'GitHub CLI is not authenticated; launching `gh auth login --web`...',
        file=sys.stderr,
    )
    result = subprocess.run(  # noqa: S603 - argv is explicit and shell=False
        [_command_path('gh'), 'auth', 'login', '--web'],
        check=False,
    )
    if result.returncode != 0:
        msg = (
            'GitHub CLI login did not complete successfully.\n\n'
            'Please rerun:\n'
            '  gh auth login --web'
        )
        raise ConfigCodexError(msg)

    if _gh_auth_status_is_authenticated():
        return

    msg = (
        'GitHub CLI login finished, but no authenticated session is available.\n\n'
        'Please verify with:\n'
        '  gh auth status'
    )
    raise ConfigCodexError(msg)


def resolve_github_token() -> str:
    """Resolve and trim the current GitHub auth token from ``gh``."""
    result = subprocess.run(  # noqa: S603 - argv is explicit and shell=False
        [_command_path('gh'), 'auth', 'token'],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        msg = (
            'Unable to resolve a GitHub token from gh.\n\n'
            'Please ensure you are logged in:\n'
            '  gh auth login'
        )
        raise ConfigCodexError(msg)

    token = result.stdout.strip()
    if token:
        return token

    msg = (
        '`gh auth token` returned an empty token.\n\n'
        'Please refresh your login:\n'
        '  gh auth login'
    )
    raise ConfigCodexError(msg)


def _gh_auth_status_is_authenticated() -> bool:
    """Return whether ``gh auth status`` reports an authenticated session."""
    result = subprocess.run(  # noqa: S603 - argv is explicit and shell=False
        [_command_path('gh'), 'auth', 'status'],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def backup_codex_config(config_path: Path, backup_dir: Path) -> str:
    """Create or initialize the Codex config file and return the backup path display."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    backup_dir.mkdir(parents=True, exist_ok=True)

    if config_path.exists():
        timestamp = datetime.now(UTC).strftime('%Y%m%d-%H%M%S')
        backup_path = backup_dir / f'config.toml.{timestamp}.bak'
        shutil.copy2(config_path, backup_path)
        return str(backup_path)

    config_path.write_text('', encoding='utf-8')
    return '(none; config did not exist)'


def update_codex_config_text(
    source: str,
    *,
    model: str,
    provider_id: str,
    base_url: str,
) -> str:
    """Return updated Codex config TOML for the local provider integration.

    The updater validates the existing TOML, replaces only the root-level
    ``model`` and ``model_provider`` keys, removes the entire
    ``model_providers.<provider_id>`` subtree (including nested subtables), and
    appends a fresh provider block for the local service. Unrelated comments,
    tables, and keys remain byte-for-byte intact aside from the touched lines.
    """
    if source.strip():
        _load_toml_document(source, context='existing Codex config')

    newline = _detect_newline(source)
    lines = source.splitlines()
    lines = _remove_provider_subtree(lines, provider_id=provider_id)
    lines = _remove_root_keys(lines, keys={'model', 'model_provider'})
    lines = _insert_root_keys(lines, model=model, provider_id=provider_id)
    lines = _append_provider_block(
        lines,
        provider_id=provider_id,
        base_url=base_url,
    )

    rendered = newline.join(lines).rstrip() + newline
    _load_toml_document(rendered, context='updated Codex config')
    return rendered


def write_updated_codex_config(
    config_path: Path,
    *,
    model: str,
    provider_id: str,
    base_url: str,
) -> None:
    """Load, update, validate, and rewrite a Codex config file in place.

    Args:
        config_path: Filesystem path to the target ``config.toml`` file.
        model: Root-level Codex model id that should be selected.
        provider_id: Provider identifier to store in ``model_provider`` and
            under the ``[model_providers.<provider_id>]`` table.
        base_url: Provider base URL that Codex should call.

    """
    source = config_path.read_text(encoding='utf-8')
    updated = update_codex_config_text(
        source,
        model=model,
        provider_id=provider_id,
        base_url=base_url,
    )
    config_path.write_text(updated, encoding='utf-8')


def ensure_provider_container(
    *,
    container_name: str,
    image: str,
    host_port: int,
    container_port: int,
    github_token: str,
) -> bool:
    """Ensure a compatible local provider container is available.

    The setup scripts should avoid unnecessary restarts during repeated local
    configuration runs. A running container is therefore reused only when its
    image, published host port, and running state all match the requested
    configuration. All other cases fall back to a clean restart.

    Args:
        container_name: Docker container name managed by the setup scripts.
        image: Requested Docker image reference for the provider container.
        host_port: Requested host port that should map to the provider service.
        container_port: Internal provider service port exposed by the image.
        github_token: GitHub token injected into a newly started container.

    Returns:
        ``True`` when an existing container was reused, otherwise ``False`` after
        starting a fresh container.

    """
    inspection = inspect_container(
        container_name=container_name,
        container_port=container_port,
    )
    if inspection is not None and should_reuse_container(
        inspection=inspection,
        image=image,
        host_port=host_port,
    ):
        return True

    restart_container(
        container_name=container_name,
        image=image,
        host_port=host_port,
        container_port=container_port,
        github_token=github_token,
    )
    return False


def restart_container(
    *,
    container_name: str,
    image: str,
    host_port: int,
    container_port: int,
    github_token: str,
) -> None:
    """Replace any existing local provider container with a fresh one."""
    if container_exists(container_name):
        run_command(['docker', 'rm', '-f', container_name], capture_output=True)

    env = dict(os.environ)
    env['GITHUB_TOKEN'] = github_token
    run_command(
        [
            'docker',
            'run',
            '-d',
            '--name',
            container_name,
            '-e',
            'GITHUB_TOKEN',
            '-p',
            f'{host_port}:{container_port}',
            image,
        ],
        env=env,
        capture_output=True,
    )


def inspect_container(
    *,
    container_name: str,
    container_port: int,
) -> InspectedContainer | None:
    """Return normalized Docker inspect data for one named container.

    Args:
        container_name: Docker container name to inspect.
        container_port: Internal service port whose published host port should be
            extracted from the container metadata.

    Returns:
        The normalized inspected container data, or ``None`` when the container
        does not exist.

    Raises:
        ConfigCodexError: If Docker returns malformed inspect output.

    """
    docker_path = _command_path('docker')
    result = subprocess.run(  # noqa: S603 - argv is explicit and shell=False
        [docker_path, 'container', 'inspect', container_name],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        msg = f'Invalid Docker inspect output for {container_name!r}: {error}'
        raise ConfigCodexError(msg) from error

    if not isinstance(payload, list) or len(payload) != 1:
        msg = f'Unexpected Docker inspect payload for {container_name!r}.'
        raise ConfigCodexError(msg)

    container_data = payload[0]
    if not isinstance(container_data, dict):
        msg = f'Unexpected Docker inspect document for {container_name!r}.'
        raise ConfigCodexError(msg)

    image = _extract_nested_string(
        item=container_data,
        path=('Config', 'Image'),
    )
    if image is None:
        msg = f'Docker inspect did not report an image for {container_name!r}.'
        raise ConfigCodexError(msg)

    running = _extract_nested_bool(
        item=container_data,
        path=('State', 'Running'),
    )
    if running is None:
        msg = f'Docker inspect did not report a running state for {container_name!r}.'
        raise ConfigCodexError(msg)

    return InspectedContainer(
        image=image,
        running=running,
        published_port=_extract_published_port(
            item=container_data,
            container_port=container_port,
        ),
    )


def should_reuse_container(
    *,
    inspection: InspectedContainer,
    image: str,
    host_port: int,
) -> bool:
    """Report whether an inspected container is safe to reuse.

    Args:
        inspection: Normalized metadata for the existing named container.
        image: Requested Docker image reference for the current script run.
        host_port: Requested host port for the provider service.

    Returns:
        ``True`` when the inspected container is running and matches both the
        requested image and host port; otherwise ``False``.

    """
    return (
        inspection.running
        and inspection.image == image
        and inspection.published_port == host_port
    )


def container_exists(container_name: str) -> bool:
    """Return whether Docker already knows about the named container."""
    docker_path = _command_path('docker')
    result = subprocess.run(  # noqa: S603 - argv is explicit and shell=False
        [docker_path, 'container', 'inspect', container_name],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def run_command(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    capture_output: bool,
) -> subprocess.CompletedProcess[str]:
    """Run an external command and raise a focused error if it fails."""
    resolved_args = [_command_path(args[0]), *args[1:]]
    result = subprocess.run(  # noqa: S603 - argv is explicit and shell=False
        resolved_args,
        check=False,
        capture_output=capture_output,
        text=True,
        env=env,
    )
    if result.returncode == 0:
        return result

    command_display = ' '.join(args)
    stderr = result.stderr.strip()
    stdout = result.stdout.strip()
    details = stderr or stdout or '(no output)'
    msg = f'Command failed: {command_display}\n{details}'
    raise ConfigCodexError(msg)


def wait_for_health(health_url: str) -> None:
    """Poll the provider health endpoint until it becomes ready."""
    for _ in range(HEALTH_CHECK_ATTEMPTS):
        try:
            _fetch_json_document(health_url)
        except ConfigCodexError:
            time.sleep(HEALTH_CHECK_DELAY_SECONDS)
        else:
            return

    msg = (
        f'Container started but the health endpoint did not become ready: {health_url}'
    )
    raise ConfigCodexError(msg)


def fetch_visible_model_ids(base_url: str) -> list[str]:
    """Fetch visible model ids from the provider's ``/openai/v1/models`` endpoint."""
    payload = _fetch_json_document(f'{base_url}/models')
    data = payload.get('data')
    if not isinstance(data, list):
        return []

    model_ids: list[str] = []
    for item in cast('list[object]', data):
        model_id = _extract_string_field(item, field_name='id')
        if model_id is not None:
            model_ids.append(model_id)

    return model_ids


def fetch_visible_anthropic_model_ids(base_url: str) -> list[str]:
    """Fetch visible model ids from the provider's ``/anthropic/v1/models`` endpoint."""
    payload = _fetch_json_document(f'{base_url}/models')
    data = payload.get('data')
    if not isinstance(data, list):
        return []

    model_ids: list[str] = []
    for item in cast('list[object]', data):
        model_id = _extract_string_field(item, field_name='id')
        if model_id is not None:
            model_ids.append(model_id)

    return model_ids


def ensure_model_is_visible(model: str, visible_models: list[str]) -> None:
    """Require the selected model id to be visible from the running provider."""
    if model in visible_models:
        return

    available_models = ', '.join(visible_models) if visible_models else '(none)'
    msg = (
        f'Requested model {model!r} is not visible from the running service.\n'
        f'Available models: {available_models}'
    )
    raise ConfigCodexError(msg)


def resolve_codex_model(
    *,
    preferred_model: str | None,
    visible_models: list[str],
) -> str:
    """Resolve the Codex model that should be persisted in config.

    Args:
        preferred_model: Optional user-specified model identifier.
        visible_models: Live model identifiers visible from the running provider.

    Returns:
        The explicit model when it is visible, otherwise the preferred visible
        default selected from the live catalog.

    Raises:
        ConfigCodexError: If the explicit model is not visible or no visible model
            can be selected automatically.

    """
    if preferred_model is not None:
        ensure_model_is_visible(preferred_model, visible_models)
        return preferred_model

    selected_model = select_default_codex_model(visible_models=visible_models)
    if selected_model is not None:
        return selected_model

    msg = 'Unable to choose a default model from the running service.'
    raise ConfigCodexError(msg)


def select_default_codex_model(*, visible_models: list[str]) -> str | None:
    """Select a preferred visible model for Codex when no explicit model is set.

    Preference order is:

    1. `gpt-5.4`
    2. `gpt-5.4-mini`
    3. `gpt-4.1`
    4. any remaining model identifier in provider order

    This keeps one-click setup aligned with the current auth-context live catalog
    while still preferring the models most likely to be a good default Codex fit.

    Args:
        visible_models: Live model identifiers visible from the provider.

    Returns:
        The preferred visible model identifier, or ``None`` when the provider
        exposes no models.

    """
    for preferred_model in ('gpt-5.4', 'gpt-5.4-mini', 'gpt-4.1'):
        if preferred_model in visible_models:
            return preferred_model

    if visible_models:
        return visible_models[0]

    return None


def _fetch_json_document(url: str) -> dict[str, object]:
    """Fetch and decode a JSON document from the local provider service."""
    parsed_url = urllib.parse.urlparse(url)
    if parsed_url.scheme not in {'http', 'https'}:
        msg = (
            f'Unsupported URL scheme for local provider request: {parsed_url.scheme!r}'
        )
        raise ConfigCodexError(msg)

    try:
        with urllib.request.urlopen(  # noqa: S310 - scheme is validated above
            url,
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as response:
            return json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        msg = f'Unable to fetch {url}: {error}'
        raise ConfigCodexError(msg) from error


def _extract_nested_string(
    *,
    item: dict[str, Any],
    path: tuple[str, ...],
) -> str | None:
    """Extract one nested string field from a JSON-like object tree.

    Args:
        item: JSON-like object tree to traverse.
        path: Object path segments that should lead to a string value.

    Returns:
        The nested string value, or ``None`` when the path is missing or typed
        differently.

    """
    current: Any = item
    for segment in path:
        if not isinstance(current, dict):
            return None
        current = current.get(segment)

    if isinstance(current, str):
        return current
    return None


def _extract_nested_bool(
    *,
    item: dict[str, Any],
    path: tuple[str, ...],
) -> bool | None:
    """Extract one nested boolean field from a JSON-like object tree.

    Args:
        item: JSON-like object tree to traverse.
        path: Object path segments that should lead to a boolean value.

    Returns:
        The nested boolean value, or ``None`` when the path is missing or typed
        differently.

    """
    current: Any = item
    for segment in path:
        if not isinstance(current, dict):
            return None
        current = current.get(segment)

    if isinstance(current, bool):
        return current
    return None


def _extract_published_port(
    *,
    item: dict[str, Any],
    container_port: int,
) -> int | None:
    """Extract the published host port for one internal container port.

    Args:
        item: JSON-like Docker inspect document for one container.
        container_port: Internal container port to resolve.

    Returns:
        The first published host port for ``container_port``, or ``None`` when
        Docker does not report a usable binding for that port.

    """
    ports = item.get('NetworkSettings')
    if not isinstance(ports, dict):
        return None

    port_bindings = ports.get('Ports')
    if not isinstance(port_bindings, dict):
        return None

    binding = port_bindings.get(f'{container_port}/tcp')
    if not isinstance(binding, list):
        return None

    for entry in binding:
        if not isinstance(entry, dict):
            continue
        host_port = entry.get('HostPort')
        if not isinstance(host_port, str):
            continue
        try:
            return int(host_port)
        except ValueError:
            return None

    return None


def _load_toml_document(source: str, *, context: str) -> dict[str, object]:
    """Parse TOML text and raise a focused error when it is invalid."""
    try:
        return tomllib.loads(source)
    except tomllib.TOMLDecodeError as error:
        msg = f'Invalid {context}: {error}'
        raise ConfigCodexError(msg) from error


def _detect_newline(source: str) -> str:
    """Choose the newline style that should be preserved in the rewritten file."""
    if '\r\n' in source:
        return '\r\n'
    return '\n'


def _parse_table_path(line: str) -> tuple[str, ...] | None:
    """Return the TOML table path for a header line, or ``None`` otherwise."""
    if line.lstrip().startswith('#'):
        return None

    match = TABLE_HEADER_PATTERN.match(line)
    if match is None:
        return None

    opener, body, closer = match.groups()
    if len(opener) != len(closer):
        return None

    return tuple(_split_dotted_key(body.strip()))


def _split_dotted_key(source: str) -> list[str]:
    """Split a TOML dotted key or table path into its component segments."""
    parts: list[str] = []
    buffer: list[str] = []
    quote_char: str | None = None
    index = 0

    while index < len(source):
        char = source[index]
        if quote_char is not None:
            if char == '\\' and quote_char == '"' and index + 1 < len(source):
                buffer.append(char)
                index += 1
                buffer.append(source[index])
            elif char == quote_char:
                quote_char = None
            else:
                buffer.append(char)
            index += 1
            continue

        if char in {'"', "'"}:
            quote_char = char
            index += 1
            continue

        if char == '.':
            parts.append(''.join(buffer).strip())
            buffer = []
            index += 1
            continue

        buffer.append(char)
        index += 1

    if quote_char is not None:
        msg = f'Unterminated quoted TOML key segment: {source!r}'
        raise ConfigCodexError(msg)

    parts.append(''.join(buffer).strip())
    return [part for part in parts if part]


def _remove_provider_subtree(lines: list[str], *, provider_id: str) -> list[str]:
    """Drop the target provider table and any nested subtables from the file."""
    result: list[str] = []
    skipping = False

    for line in lines:
        table_path = _parse_table_path(line)
        if table_path is not None:
            matches_provider = _is_provider_table_path(
                table_path,
                provider_id=provider_id,
            )
            if skipping and not matches_provider:
                skipping = False

            if matches_provider:
                skipping = True
                continue

        if skipping:
            continue

        result.append(line)

    return result


def _is_provider_table_path(table_path: tuple[str, ...], *, provider_id: str) -> bool:
    """Report whether a table path belongs to the target model provider subtree."""
    return (
        len(table_path) >= PROVIDER_TABLE_PREFIX_LENGTH
        and table_path[0] == 'model_providers'
        and table_path[1] == provider_id
    )


def _remove_root_keys(lines: list[str], *, keys: set[str]) -> list[str]:
    """Remove matching root-level assignments before the first TOML table."""
    result: list[str] = []
    seen_table = False

    for line in lines:
        if _parse_table_path(line) is not None:
            seen_table = True
            result.append(line)
            continue

        if seen_table:
            result.append(line)
            continue

        match = ROOT_KEY_PATTERN.match(line)
        if match is not None and match.group(1) in keys:
            continue

        result.append(line)

    return result


def _insert_root_keys(
    lines: list[str],
    *,
    model: str,
    provider_id: str,
) -> list[str]:
    """Insert the managed root-level keys near the start of the document."""
    insertion_index = 0
    while insertion_index < len(lines):
        stripped = lines[insertion_index].strip()
        if stripped and not stripped.startswith('#'):
            break
        insertion_index += 1

    assignments = [
        f'model = {_render_basic_string(model)}',
        f'model_provider = {_render_basic_string(provider_id)}',
    ]
    return lines[:insertion_index] + assignments + lines[insertion_index:]


def _append_provider_block(
    lines: list[str],
    *,
    provider_id: str,
    base_url: str,
) -> list[str]:
    """Append the managed provider table using a stable normalized layout."""
    result = list(lines)
    while result and not result[-1].strip():
        result.pop()

    provider_header = _render_table_path(('model_providers', provider_id))
    provider_block = [
        provider_header,
        f'name = {_render_basic_string(DEFAULT_PROVIDER_DISPLAY_NAME)}',
        f'base_url = {_render_basic_string(base_url)}',
        'wire_api = "responses"',
    ]

    if result:
        result.append('')
    result.extend(provider_block)
    return result


def _render_table_path(path: tuple[str, ...]) -> str:
    """Render a TOML table path, quoting segments only when required."""
    rendered_parts = [
        part if BARE_KEY_PATTERN.fullmatch(part) else json.dumps(part) for part in path
    ]
    return '[' + '.'.join(rendered_parts) + ']'


def _render_basic_string(value: str) -> str:
    """Render a TOML basic string using JSON-compatible escaping."""
    return json.dumps(value)


def _extract_string_field(item: object, *, field_name: str) -> str | None:
    """Extract one string field from a JSON object-like value when present."""
    if not isinstance(item, dict):
        return None

    typed_item = cast('dict[object, object]', item)
    for key, value in typed_item.items():
        if key == field_name and isinstance(value, str):
            return value

    return None


def _parse_port(value: str) -> int:
    """Validate a CLI port argument and return it as an integer."""
    error_message = 'Port must be an integer between 1 and 65535.'
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(error_message) from error

    if 1 <= port <= MAX_PORT:
        return port

    raise argparse.ArgumentTypeError(error_message)


def _command_path(command: str) -> str:
    """Resolve an executable from ``PATH`` or raise a user-facing configuration error."""
    path = shutil.which(command)
    if path is not None:
        return path

    msg = f'Required command not found: {command}'
    raise ConfigCodexError(msg)


def main(argv: list[str] | None = None) -> int:
    """Run the CLI entrypoint and print the resulting local Codex configuration."""
    options = parse_args(argv)

    try:
        result = run_config_codex(options)
    except ConfigCodexError as error:
        print(error, file=sys.stderr)
        return 1

    print(f'Configured Codex to use {result.base_url}')
    print(f'Container name: {result.container_name}')
    print(f'Image: {result.image}')
    print(f'Model: {result.model}')
    print(f'Backup: {result.backup_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
