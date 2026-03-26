"""Shared helpers for real-runtime test scenarios."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from shutil import which

from copilot import CopilotClient, SubprocessConfig

_REPO_ROOT = Path(__file__).resolve().parents[1]
_GH_EXECUTABLE = which('gh')


def resolve_github_token() -> str | None:
    """Resolve a GitHub auth token for real-runtime test execution.

    The helper first honors explicit environment variables so callers can
    control which credential is used. When no environment override is present,
    it falls back to ``gh auth token`` if the GitHub CLI is installed and
    already authenticated.

    Returns:
        The resolved bearer token when one is available, otherwise ``None``.

    """
    for variable_name in ('GITHUB_TOKEN', 'GH_TOKEN'):
        token = os.environ.get(variable_name, '').strip()
        if token:
            return token

    if _GH_EXECUTABLE is None:
        return None

    token_result = subprocess.run(  # noqa: S603
        [_GH_EXECUTABLE, 'auth', 'token'],
        cwd=_REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    token = token_result.stdout.strip()
    if token_result.returncode != 0 or not token:
        return None

    return token


async def list_live_model_ids(
    *,
    github_token: str,
    working_directory: str | None = None,
) -> list[str]:
    """List the live Copilot model identifiers visible to one auth context.

    Args:
        github_token: GitHub bearer token used to authenticate the SDK client.
        working_directory: Optional working directory forwarded into the
            subprocess-backed SDK client.

    Returns:
        The stable, de-duplicated list of live Copilot model identifiers
        returned by ``CopilotClient.list_models()`` for the supplied auth
        context.

    """
    client = CopilotClient(
        SubprocessConfig(
            cwd=working_directory,
            github_token=github_token,
        ),
        auto_start=False,
    )
    try:
        await client.start()
        models = await client.list_models()
    finally:
        await client.stop()

    model_ids = [
        model_id
        for model in models
        if isinstance((model_id := getattr(model, 'id', None)), str) and model_id
    ]
    return list(dict.fromkeys(model_ids))
