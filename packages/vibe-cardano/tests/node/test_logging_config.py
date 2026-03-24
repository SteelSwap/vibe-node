"""Tests for vibe.cardano.node.logging_config."""

from __future__ import annotations

import json
import logging
import os
from unittest.mock import patch

from vibe.cardano.node.logging_config import JsonFormatter, configure_logging


class TestJsonFormatter:
    def test_produces_valid_json(self) -> None:
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="hello %s",
            args=("world",),
            exc_info=None,
        )
        output = formatter.format(record)
        obj = json.loads(output)
        assert obj["level"] == "INFO"
        assert obj["logger"] == "test.logger"
        assert obj["message"] == "hello world"
        assert "timestamp" in obj

    def test_includes_extra_fields(self) -> None:
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test",
            args=(),
            exc_info=None,
        )
        record.slot = 42  # type: ignore[attr-defined]
        record.event = "forge.block"  # type: ignore[attr-defined]
        output = formatter.format(record)
        obj = json.loads(output)
        assert obj["slot"] == 42
        assert obj["event"] == "forge.block"

    def test_handles_exception(self) -> None:
        formatter = JsonFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            record = logging.LogRecord(
                name="test",
                level=logging.ERROR,
                pathname="",
                lineno=0,
                msg="failed",
                args=(),
                exc_info=sys.exc_info(),
            )
        output = formatter.format(record)
        obj = json.loads(output)
        assert "exception" in obj
        assert "ValueError: boom" in obj["exception"]

    def test_non_serializable_extra(self) -> None:
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test",
            args=(),
            exc_info=None,
        )
        record.data = b"\x00\x01"  # type: ignore[attr-defined]
        output = formatter.format(record)
        obj = json.loads(output)  # should not raise
        assert "data" in obj


class TestConfigureLogging:
    def test_default_format_is_text(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VIBE_LOG_FORMAT", None)
            configure_logging()
            root = logging.getLogger()
            assert len(root.handlers) == 1
            assert not isinstance(root.handlers[0].formatter, JsonFormatter)

    def test_json_format(self) -> None:
        with patch.dict(os.environ, {"VIBE_LOG_FORMAT": "json"}):
            configure_logging()
            root = logging.getLogger()
            assert isinstance(root.handlers[0].formatter, JsonFormatter)

    def test_sets_level(self) -> None:
        configure_logging(level=logging.DEBUG)
        root = logging.getLogger()
        assert root.level == logging.DEBUG

    def test_explicit_fmt_overrides_env(self) -> None:
        with patch.dict(os.environ, {"VIBE_LOG_FORMAT": "text"}):
            configure_logging(fmt="json")
            root = logging.getLogger()
            assert isinstance(root.handlers[0].formatter, JsonFormatter)
