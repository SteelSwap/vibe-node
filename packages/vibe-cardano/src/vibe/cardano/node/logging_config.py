"""Logging configuration for vibe-node.

Supports two formats:
- text (default): human-readable ``%(asctime)s %(name)s %(levelname)s %(message)s``
- json: structured JSON, one object per line, for log aggregation pipelines

Set via ``VIBE_LOG_FORMAT=json`` environment variable.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON objects.

    Output fields: timestamp, level, logger, message, plus any ``extra``
    fields passed via the record's ``__dict__``.
    """

    # Fields that are part of the standard LogRecord — not user extras
    _BUILTIN_ATTRS = frozenset(
        {
            "args",
            "created",
            "exc_info",
            "exc_text",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "message",
            "module",
            "msecs",
            "msg",
            "name",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "thread",
            "threadName",
            "taskName",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()

        obj: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.message,
        }

        # Merge extra fields
        for key, value in record.__dict__.items():
            if key not in self._BUILTIN_ATTRS and not key.startswith("_"):
                obj[key] = value

        if record.exc_info and record.exc_info[1] is not None:
            obj["exception"] = self.formatException(record.exc_info)

        return json.dumps(obj, default=str)


def configure_logging(
    *,
    level: int = logging.INFO,
    fmt: str | None = None,
    error_log_path: str | None = None,
) -> None:
    """Configure the root logger for vibe-node.

    Parameters
    ----------
    level:
        Logging level (default ``INFO``).
    fmt:
        Override format. If ``None``, reads ``VIBE_LOG_FORMAT`` env var.
        ``"json"`` → :class:`JsonFormatter`, anything else → text format.
    error_log_path:
        If set, write ERROR+ messages to this file. If ``None``, reads
        ``VIBE_ERROR_LOG`` env var. Enables post-run debugging without
        wading through INFO noise.
    """
    log_format = fmt or os.environ.get("VIBE_LOG_FORMAT", "text")

    handler = logging.StreamHandler()

    if log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))

    root = logging.getLogger()
    root.setLevel(level)
    # Remove existing handlers to avoid duplicates
    root.handlers.clear()
    root.addHandler(handler)

    # Optional error-only file handler for debugging
    error_path = error_log_path or os.environ.get("VIBE_ERROR_LOG")
    if error_path:
        error_handler = logging.FileHandler(error_path, mode="a")
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(name)s %(levelname)s %(message)s\n"
                "  %(pathname)s:%(lineno)d\n"
            )
        )
        root.addHandler(error_handler)
