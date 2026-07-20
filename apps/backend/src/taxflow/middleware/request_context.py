"""Request-scoped context for logging (Task 2a).

``request_id_var`` holds the current request's id so any log record emitted
while handling a request can be tagged with it. ``RequestIdFilter`` copies the
contextvar value onto each ``LogRecord`` as ``record.request_id`` so the
JSON formatter can serialise it.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    """Attach the request-scoped ``request_id`` to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True
