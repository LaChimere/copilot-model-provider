"""Service entrypoint helpers for the provider package."""

from __future__ import annotations

import os
import shutil
from typing import Final

import structlog

from .config import ProviderSettings

ASGI_APP_IMPORT_PATH = 'copilot_model_provider.app:app'
ASGI_FACTORY_IMPORT_PATH = 'copilot_model_provider.app:create_app'
UVICORN_EXECUTABLE_NAME = 'uvicorn'

_logger = structlog.get_logger(__name__)

_SERVICE_SUMMARY: Final[str] = 'copilot-model-provider is a service package.'
_ASGI_SERVER_REQUIREMENT: Final[str] = (
    'An installed ASGI server such as uvicorn is required to run the service.'
)


def build_startup_guidance_fields() -> dict[str, str]:
    """Build the structured startup-guidance fields for service entrypoints."""
    return {
        'summary': _SERVICE_SUMMARY,
        'asgi_server_requirement': _ASGI_SERVER_REQUIREMENT,
        'package_command': 'copilot-model-provider',
        'asgi_app_import_path': ASGI_APP_IMPORT_PATH,
        'asgi_factory_import_path': ASGI_FACTORY_IMPORT_PATH,
        'example_command': f'uvicorn {ASGI_APP_IMPORT_PATH}',
        'factory_command': f'uvicorn {ASGI_FACTORY_IMPORT_PATH} --factory',
    }


def build_startup_guidance() -> str:
    """Build startup guidance for the package's thin service entrypoint."""
    fields = build_startup_guidance_fields()
    return (
        f'{fields["summary"]}\n'
        f'{fields["asgi_server_requirement"]}\n'
        'Run the packaged service entrypoint:\n'
        f'  {fields["package_command"]}\n'
        'Or invoke uvicorn directly:\n'
        f'  {fields["example_command"]}\n'
        'Use the factory entrypoint when explicit app construction is needed:\n'
        f'  {fields["factory_command"]}\n'
    )


def build_server_command(*, settings: ProviderSettings) -> tuple[str, ...]:
    """Build the uvicorn command used by the package entrypoint."""
    return (
        UVICORN_EXECUTABLE_NAME,
        ASGI_FACTORY_IMPORT_PATH,
        '--factory',
        '--host',
        settings.server_host,
        '--port',
        str(settings.server_port),
    )


def _resolve_uvicorn_executable() -> str:
    """Resolve the installed uvicorn executable path for process replacement."""
    executable_path = shutil.which(UVICORN_EXECUTABLE_NAME)
    if executable_path is None:
        msg = (
            'copilot-model-provider requires an installed "uvicorn" executable '
            'to start the HTTP service'
        )
        raise RuntimeError(msg)

    return executable_path


def _exec_server_command(*, executable_path: str, command: tuple[str, ...]) -> None:
    """Replace the current process with the configured uvicorn server process."""
    os.execv(executable_path, command)  # noqa: S606 - formal process entrypoint


def main() -> None:
    """Start the provider through the formal external ASGI server entrypoint."""
    settings = ProviderSettings.from_env()
    command = build_server_command(settings=settings)
    executable_path = _resolve_uvicorn_executable()

    _logger.info(
        'service_starting',
        executable=UVICORN_EXECUTABLE_NAME,
        host=settings.server_host,
        port=settings.server_port,
        factory_import_path=ASGI_FACTORY_IMPORT_PATH,
    )
    _exec_server_command(executable_path=executable_path, command=command)
