"""Unit tests for structlog/stdlb logging configuration helpers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from copilot_model_provider import logging_config

if TYPE_CHECKING:
    import pytest
    import structlog


def test_build_log_config_targets_root_and_uvicorn_loggers() -> None:
    """Verify that the logging config routes uvicorn and root logs together."""
    config = logging_config.build_log_config(level='DEBUG')

    assert config['root'] == {'handlers': ['default'], 'level': 'DEBUG'}
    assert config['loggers']['uvicorn']['handlers'] == ['default']
    assert config['loggers']['uvicorn.error']['propagate'] is False
    assert config['loggers']['uvicorn.access']['level'] == 'DEBUG'


def test_drop_color_message_removes_uvicorn_color_payload() -> None:
    """Verify that redundant uvicorn color-message fields are stripped."""
    event_dict: structlog.typing.EventDict = {
        'event': 'Started server process [1]',
        'color_message': '\u001b[32mStarted server process [1]\u001b[0m',
    }

    result = logging_config.drop_color_message(
        logging.getLogger('uvicorn.error'),
        'info',
        event_dict,
    )

    assert result == {'event': 'Started server process [1]'}


def test_configure_logging_applies_dict_config_and_structlog_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that logging setup configures both stdlib logging and structlog."""
    captured: dict[str, Any] = {}

    def fake_dict_config(config: dict[str, Any]) -> None:
        """Capture the stdlib logging config payload."""
        captured['dict_config'] = config

    def fake_structlog_configure(**kwargs: Any) -> None:
        """Capture structlog's runtime configuration payload."""
        captured['structlog_kwargs'] = kwargs

    monkeypatch.setattr(logging_config.logging.config, 'dictConfig', fake_dict_config)
    monkeypatch.setattr(logging_config.structlog, 'configure', fake_structlog_configure)

    logging_config.configure_logging(level='WARNING')

    assert captured['dict_config']['root']['level'] == 'WARNING'
    assert isinstance(
        captured['structlog_kwargs']['logger_factory'],
        logging_config.structlog.stdlib.LoggerFactory,
    )
