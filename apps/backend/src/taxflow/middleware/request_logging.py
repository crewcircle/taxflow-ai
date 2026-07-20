"""Request-logging middleware (Task 2a).

Reads (or generates) an ``X-Request-ID``, binds it to the request-scoped
contextvar so every log line emitted during the request carries it, times the
request with ``perf_counter``, and emits exactly ONE structured ``info`` access
record with ``method``/``path``/``status_code``/``latency_ms``/``client_id``.
The ``X-Request-ID`` is echoed back on the response.

``client_id`` is read from ``request.state.client_id`` if a route dependency
set it (see ``middleware/auth.get_current_client``) — the middleware never
re-runs authentication.
"""

from __future__ import annotations

import logging
import uuid
from time import perf_counter

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from taxflow.middleware.request_context import request_id_var

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        start = perf_counter()
        try:
            try:
                response = await call_next(request)
            except Exception:
                # An unhandled route exception still gets exactly one access
                # record (status 500) before we re-raise so FastAPI's normal
                # error handling produces the 500 response. We cannot echo
                # X-Request-ID on that generated error response from here —
                # BaseHTTPMiddleware has no handle on the response object when
                # call_next raises — but the access record (which carries the
                # request_id via the contextvar) is guaranteed.
                latency_ms = round((perf_counter() - start) * 1000, 3)
                logger.info(
                    "request",
                    extra={
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": 500,
                        "latency_ms": latency_ms,
                        "client_id": getattr(request.state, "client_id", None),
                    },
                )
                raise

            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            latency_ms = round((perf_counter() - start) * 1000, 3)
            logger.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "latency_ms": latency_ms,
                    "client_id": getattr(request.state, "client_id", None),
                },
            )
            return response
        finally:
            request_id_var.reset(token)
