"""Structured JSON logging setup (Task 2a).

``configure_logging()`` installs a single stdout ``StreamHandler`` with a
stdlib ``JsonFormatter`` (no third-party dependency) that serialises each
record as a one-line JSON object with ``timestamp``, ``level``, ``logger``,
``message`` and ``request_id`` (populated from the request-scoped contextvar via
``RequestIdFilter``), plus any ``extra`` fields passed to the logging call.

uvicorn's own access logger is silenced here — the request-logging middleware
emits the single structured access line instead.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from taxflow.config import settings
from taxflow.middleware.request_context import RequestIdFilter

# Attributes present on every ``LogRecord``; anything NOT in here (and not one
# of the handful we serialise explicitly) is treated as caller-supplied
# ``extra`` and folded into the JSON payload.
_RESERVED = frozenset(
    logging.makeLogRecord({}).__dict__.keys()
) | {"request_id", "message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    """Serialise a ``LogRecord`` to a single-line JSON string."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)

        # Fold caller-supplied ``extra`` fields into the payload.
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value

        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """Install the JSON stdout handler and align framework log levels.

    Idempotent: replaces any handlers previously installed on the root logger so
    repeated calls (e.g. in tests) don't stack duplicate handlers.
    """
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
        logger.setLevel(level)

    # Disable uvicorn's default access log — our middleware emits the access
    # line as a structured record instead.
    access = logging.getLogger("uvicorn.access")
    access.handlers = []
    access.propagate = False
    access.disabled = True
