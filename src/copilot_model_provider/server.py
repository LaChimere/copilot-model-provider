"""Service entrypoint helpers for the provider package."""

from __future__ import annotations

from typing import Final, TypedDict

import structlog
import uvicorn

from .config import ProviderSettings
from .logging_config import configure_logging

ASGI_APP_IMPORT_PATH = 'copilot_model_provider.app:app'
ASGI_FACTORY_IMPORT_PATH = 'copilot_model_provider.app:create_app'
UVICORN_EXECUTABLE_NAME = 'uvicorn'

_logger = structlog.get_logger(__name__)

_SERVICE_SUMMARY: Final[str] = 'copilot-model-provider is a service package.'
_ASGI_SERVER_REQUIREMENT: Final[str] = (
    'An installed ASGI server such as uvicorn is required to run the service.'
)


class UvicornServerKwargs(TypedDict):
    """Typed uvicorn keyword arguments used by the service entrypoint."""

    app: str
    factory: bool
    host: str
    port: int
    access_log: bool
    log_config: None


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


def build_server_kwargs(*, settings: ProviderSettings) -> UvicornServerKwargs:
    """Build the uvicorn kwargs used by the package entrypoint.

    Args:
        settings: Validated provider settings for the running service process.

    Returns:
        A keyword-argument mapping suitable for ``uvicorn.run``.

    """
    return {
        'app': ASGI_FACTORY_IMPORT_PATH,
        'factory': True,
        'host': settings.server_host,
        'port': settings.server_port,
        'access_log': False,
        'log_config': None,
    }


def main() -> None:
    """Start the provider through the formal external ASGI server entrypoint."""
    configure_logging()
    settings = ProviderSettings.from_env()
    server_kwargs = build_server_kwargs(settings=settings)

    _logger.info(
        'service_starting',
        executable=UVICORN_EXECUTABLE_NAME,
        host=settings.server_host,
        port=settings.server_port,
        factory_import_path=ASGI_FACTORY_IMPORT_PATH,
        access_log=False,
    )
    uvicorn.run(**server_kwargs)
