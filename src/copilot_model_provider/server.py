"""Service entrypoint helpers for the provider package."""

from typing import Final

import structlog

ASGI_APP_IMPORT_PATH = 'copilot_model_provider.app:app'
ASGI_FACTORY_IMPORT_PATH = 'copilot_model_provider.app:create_app'

_logger = structlog.get_logger(__name__)

_SERVICE_SUMMARY: Final[str] = (
    'copilot-model-provider is a service package, not an end-user CLI.'
)
_ASGI_SERVER_REQUIREMENT: Final[str] = (
    'Use an installed ASGI server such as uvicorn to run the service.'
)


def build_startup_guidance_fields() -> dict[str, str]:
    """Build the structured startup-guidance fields for service entrypoints.

    Returns:
        A structured mapping describing the service-first entrypoint guidance,
        including the summary, external ASGI server requirement, and example
        startup commands.

    """
    return {
        'summary': _SERVICE_SUMMARY,
        'asgi_server_requirement': _ASGI_SERVER_REQUIREMENT,
        'asgi_app_import_path': ASGI_APP_IMPORT_PATH,
        'asgi_factory_import_path': ASGI_FACTORY_IMPORT_PATH,
        'example_command': f'uvicorn {ASGI_APP_IMPORT_PATH}',
        'factory_command': f'uvicorn {ASGI_FACTORY_IMPORT_PATH} --factory',
    }


def build_startup_guidance() -> str:
    """Build startup guidance for the package's thin service entrypoint.

    Returns:
        A human-readable message that explains the package's service-first
        operating model and shows the supported import paths for starting the
        ASGI application with an external server such as ``uvicorn``.

    """
    fields = build_startup_guidance_fields()
    return (
        f'{fields["summary"]}\n'
        f'{fields["asgi_server_requirement"]}\n'
        'For example:\n'
        f'  {fields["example_command"]}\n'
        'or use the factory entrypoint when explicit app construction is needed:\n'
        f'  {fields["factory_command"]}\n'
    )


def main() -> None:
    """Log service startup guidance for package-based invocation.

    This thin entrypoint preserves ``python -m copilot_model_provider`` and the
    installed console script for local discovery while making it explicit that
    the repository's main deliverable is the HTTP/ASGI service, not a separate
    interactive CLI product.

    """
    _logger.info('service_entrypoint_guidance', **build_startup_guidance_fields())
