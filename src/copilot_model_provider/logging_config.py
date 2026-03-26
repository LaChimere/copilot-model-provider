"""Logging configuration helpers for structlog-backed service output."""

from __future__ import annotations

import logging
import logging.config
from typing import Any

import structlog


def drop_color_message(
    _logger: logging.Logger,
    _method_name: str,
    event_dict: structlog.typing.EventDict,
) -> structlog.typing.EventDict:
    """Remove uvicorn's optional colorized message field before rendering.

    Args:
        _logger: Logger currently emitting the event.
        _method_name: Logging method currently being processed.
        event_dict: Structured event payload under transformation.

    Returns:
        The event payload without uvicorn's redundant ``color_message`` field.

    """
    del _logger, _method_name
    event_dict.pop('color_message', None)
    return event_dict


def build_log_config(*, level: str = 'INFO') -> dict[str, Any]:
    """Build the stdlib logging configuration used by the service runtime.

    Args:
        level: Root logging level to apply to the service and uvicorn loggers.

    Returns:
        A ``logging.config.dictConfig``-compatible dictionary that routes both
        structlog events and foreign stdlib logs through the same structlog
        renderer.

    """
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt='%Y-%m-%d %H:%M:%S'),
        drop_color_message,
    ]
    return {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'structlog': {
                '()': structlog.stdlib.ProcessorFormatter,
                'foreign_pre_chain': shared_processors,
                'processors': [
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    structlog.processors.StackInfoRenderer(),
                    structlog.processors.format_exc_info,
                    structlog.dev.ConsoleRenderer(colors=False),
                ],
            }
        },
        'handlers': {
            'default': {
                'class': 'logging.StreamHandler',
                'formatter': 'structlog',
            }
        },
        'root': {
            'handlers': ['default'],
            'level': level,
        },
        'loggers': {
            'uvicorn': {
                'handlers': ['default'],
                'level': level,
                'propagate': False,
            },
            'uvicorn.error': {
                'handlers': ['default'],
                'level': level,
                'propagate': False,
            },
            'uvicorn.access': {
                'handlers': ['default'],
                'level': level,
                'propagate': False,
            },
        },
    }


def configure_logging(*, level: str = 'INFO') -> None:
    """Configure structlog and stdlib logging for the service process.

    Args:
        level: Root logging level to apply to the service process.

    """
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt='%Y-%m-%d %H:%M:%S'),
        drop_color_message,
    ]
    logging.config.dictConfig(build_log_config(level=level))
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
