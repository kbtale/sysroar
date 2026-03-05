import logging
import logging.handlers
import pytest
from unittest.mock import patch, MagicMock
import os

# Set dummy environment variables before importing the agent module
os.environ.setdefault("SYSROAR_SERVER_ID", "test-server-id")
os.environ.setdefault("SYSROAR_LOGSTASH_HOST", "localhost")
os.environ.setdefault("SYSROAR_LOGSTASH_PORT", "5000")

from agent.client import logger, configure_syslog_handler, SERVER_ID


class TestLoggerInitialization:
    """Tests for the agent's logger setup at import time."""

    def test_logger_has_console_handler(self):
        """The logger must always have a StreamHandler for stdout output."""
        handler_types = [type(h) for h in logger.handlers]
        assert logging.StreamHandler in handler_types

    def test_logger_has_syslog_handler(self):
        """On a normal startup, the logger should also have a SysLogHandler."""
        handler_types = [type(h) for h in logger.handlers]
        assert logging.handlers.SysLogHandler in handler_types

    def test_syslog_handler_address(self):
        """The SysLogHandler must point to the configured Logstash host and port."""
        syslog_handler = next(
            h for h in logger.handlers
            if isinstance(h, logging.handlers.SysLogHandler)
        )
        assert syslog_handler.address == ("localhost", 5000)

    def test_syslog_handler_formatter_includes_server_id(self):
        """The log format must embed the SERVER_ID for multi-tenant correlation."""
        syslog_handler = next(
            h for h in logger.handlers
            if isinstance(h, logging.handlers.SysLogHandler)
        )
        assert f"sysroar-agent[{SERVER_ID}]" in syslog_handler.formatter._fmt


class TestConfigureSyslogHandler:
    """Tests for the configure_syslog_handler function directly."""

    def setup_method(self):
        """Remove any existing SysLogHandlers before each test to isolate side effects."""
        for h in logger.handlers[:]:
            if isinstance(h, logging.handlers.SysLogHandler):
                logger.removeHandler(h)

    def teardown_method(self):
        """Re-attach the default handler after each test so other tests aren't affected."""
        configure_syslog_handler("localhost", 5000, SERVER_ID)

    def test_success_returns_handler(self):
        """On success, the function should return the created SysLogHandler."""
        handler = configure_syslog_handler("localhost", 5000, "test-id")
        assert handler is not None
        assert isinstance(handler, logging.handlers.SysLogHandler)

    def test_success_attaches_to_logger(self):
        """On success, the handler must be attached to the agent logger."""
        handler = configure_syslog_handler("localhost", 5000, "test-id")
        assert handler in logger.handlers

    def test_success_formatter_uses_given_server_id(self):
        """The formatter must use the server_id passed as an argument, not a global."""
        handler = configure_syslog_handler("localhost", 5000, "my-custom-id")
        assert "sysroar-agent[my-custom-id]" in handler.formatter._fmt

    @patch("agent.client.logging.handlers.SysLogHandler", side_effect=ConnectionRefusedError("Connection refused"))
    def test_failure_returns_none(self, mock_handler_class):
        """If the SysLogHandler constructor raises, the function must return None."""
        result = configure_syslog_handler("unreachable-host", 9999, "test-id")
        assert result is None

    @patch("agent.client.logging.handlers.SysLogHandler", side_effect=OSError("Network is unreachable"))
    def test_failure_does_not_crash(self, mock_handler_class):
        """The agent must not crash if Logstash is unavailable."""
        result = configure_syslog_handler("unreachable-host", 9999, "test-id")
        assert result is None

    @patch("agent.client.logging.handlers.SysLogHandler", side_effect=ConnectionRefusedError("Connection refused"))
    def test_failure_does_not_add_handler(self, mock_handler_class):
        """On failure, no new handler should be added to the logger."""
        handlers_before = len(logger.handlers)
        configure_syslog_handler("unreachable-host", 9999, "test-id")
        assert len(logger.handlers) == handlers_before
