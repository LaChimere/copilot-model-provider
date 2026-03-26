"""Pytest fixtures for container-backed integration tests."""

from __future__ import annotations

import socket
import subprocess
import time
from pathlib import Path
from shutil import which
from typing import TYPE_CHECKING
from uuid import uuid4

import httpx
import pytest

from tests.runtime_support import resolve_github_token

if TYPE_CHECKING:
    from collections.abc import Iterator

_REPO_ROOT = Path(__file__).resolve().parents[2]
_IMAGE_TAG = f'copilot-model-provider:integration-{uuid4().hex[:12]}'
_CONTAINER_NAME = f'copilot-model-provider-integration-{uuid4().hex[:12]}'
_CONTAINER_PORT = 8000
_READY_TIMEOUT_SECONDS = 90.0
_REQUEST_TIMEOUT = httpx.Timeout(180.0)
_DOCKER_EXECUTABLE = which('docker')


def _require_executable(*, path: str | None, name: str) -> str:
    """Return an absolute executable path or skip the suite when unavailable.

    Args:
        path: Resolved executable path returned by ``shutil.which``.
        name: Human-readable executable name for the skip message.

    Returns:
        The resolved executable path.

    Raises:
        pytest.SkipTest: If the executable is unavailable in the current environment.

    """
    if path is None:
        pytest.skip(f'Container-backed integration tests require `{name}` on PATH.')

    return path


def _run_docker_command(
    *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run one Docker CLI command relative to the repository root.

    Args:
        *args: Command-line arguments that follow the ``docker`` executable.
        check: Whether to raise ``CalledProcessError`` on non-zero exit.

    Returns:
        The completed subprocess result with captured text output.

    """
    docker_executable = _require_executable(path=_DOCKER_EXECUTABLE, name='docker')
    return subprocess.run(  # noqa: S603
        [docker_executable, *args],
        cwd=_REPO_ROOT,
        check=check,
        capture_output=True,
        text=True,
    )


def _resolve_github_token() -> str:
    """Resolve the GitHub auth token used for real-runtime integration tests.

    Returns:
        The bearer token that should be forwarded to the containerized provider.

    Raises:
        pytest.SkipTest: If no usable GitHub auth token is available.

    """
    token = resolve_github_token()
    if token is None:
        pytest.skip(
            'Container-backed integration tests require a real GitHub auth token '
            'via GITHUB_TOKEN/GH_TOKEN or `gh auth token`.'
        )

    return token


def _allocate_host_port() -> int:
    """Allocate an ephemeral localhost port for the container mapping.

    Returns:
        A currently free localhost TCP port.

    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(('127.0.0.1', 0))
        probe.listen(1)
        return int(probe.getsockname()[1])


def _wait_for_container(base_url: str) -> None:
    """Poll the containerized provider until the HTTP endpoint responds.

    Args:
        base_url: Root base URL for the containerized provider.

    Raises:
        RuntimeError: If the provider does not become ready before the timeout.

    """
    deadline = time.monotonic() + _READY_TIMEOUT_SECONDS
    last_error: str | None = None
    with httpx.Client(base_url=base_url, timeout=5.0) as client:
        while time.monotonic() < deadline:
            try:
                response = client.get('/v1/models')
                if response.status_code == 200:
                    return
                last_error = f'unexpected status {response.status_code}'
            except httpx.HTTPError as error:
                last_error = str(error)
            time.sleep(1.0)

    logs = _run_docker_command('logs', _CONTAINER_NAME, check=False)
    raise RuntimeError(
        'Timed out waiting for the integration test container to become ready. '
        f'Last error: {last_error or "unknown"}.\n'
        f'Container logs:\n{logs.stdout}{logs.stderr}'
    )


@pytest.fixture(scope='session')
def integration_image() -> Iterator[str]:
    """Build the production image used by the black-box integration suite.

    Yields:
        The Docker image tag built from the current repository contents.

    """
    _run_docker_command('build', '--tag', _IMAGE_TAG, '.')
    try:
        yield _IMAGE_TAG
    finally:
        _run_docker_command('rmi', '--force', _IMAGE_TAG, check=False)


@pytest.fixture(scope='session')
def integration_github_token() -> str:
    """Return the real GitHub auth token for containerized requests."""
    return _resolve_github_token()


@pytest.fixture(scope='session')
def integration_base_url(integration_image: str) -> Iterator[str]:
    """Start the production container and expose its base URL for tests.

    Args:
        integration_image: The Docker image tag built for this pytest session.

    Yields:
        The localhost base URL for the running test container.

    """
    host_port = _allocate_host_port()
    _run_docker_command('rm', '--force', _CONTAINER_NAME, check=False)
    _run_docker_command(
        'run',
        '--detach',
        '--name',
        _CONTAINER_NAME,
        '--publish',
        f'{host_port}:{_CONTAINER_PORT}',
        integration_image,
    )
    base_url = f'http://127.0.0.1:{host_port}'
    _wait_for_container(base_url)
    try:
        yield base_url
    finally:
        _run_docker_command('rm', '--force', _CONTAINER_NAME, check=False)


@pytest.fixture
def integration_client(integration_base_url: str) -> Iterator[httpx.Client]:
    """Create an HTTP client connected to the running integration container.

    Args:
        integration_base_url: Base URL of the running integration container.

    Yields:
        A synchronous ``httpx.Client`` configured for long-running real-runtime calls.

    """
    with httpx.Client(
        base_url=integration_base_url, timeout=_REQUEST_TIMEOUT
    ) as client:
        yield client
