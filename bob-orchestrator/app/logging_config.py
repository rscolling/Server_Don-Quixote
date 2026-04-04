"""Structured JSON logging for BOB.

All log output is JSON — one object per line. Parseable by jq, Loki,
Datadog, or any log aggregation tool.

Usage:
    from app.logging_config import setup_logging
    setup_logging()  # call once at startup
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone


LOG_LEVEL = os.getenv("BOB_LOG_LEVEL", "INFO").upper()
LOG_FORMAT = os.getenv("BOB_LOG_FORMAT", "json")  # "json" or "text"


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }

        # Add source location for warnings and errors
        if record.levelno >= logging.WARNING:
            entry["file"] = f"{record.filename}:{record.lineno}"

        # Add exception info if present
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = self.formatException(record.exc_info)

        # Add extra fields if attached to the record
        for key in ("task_id", "tool", "user", "service", "duration_ms",
                     "status_code", "breaker", "attempt", "ip"):
            val = getattr(record, key, None)
            if val is not None:
                entry[key] = val

        return json.dumps(entry, default=str)


class TextFormatter(logging.Formatter):
    """Standard text formatter — fallback for development."""

    def __init__(self):
        super().__init__(
            fmt="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


def setup_logging():
    """Configure root logger with JSON or text output."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    # Remove existing handlers
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)

    if LOG_FORMAT == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(TextFormatter())

    root.addHandler(handler)

    # Quiet down noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


def log_with_context(logger: logging.Logger, level: int, msg: str, **kwargs):
    """Log a message with extra structured fields.

    Usage:
        log_with_context(logger, logging.INFO, "Tool executed",
                         tool="check_email", duration_ms=142)
    """
    logger.log(level, msg, extra=kwargs)
