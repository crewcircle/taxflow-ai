"""Task 2a — structured JSON logging + request-id middleware tests."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from taxflow.logging_config import (
    _HANDLER_MARKER,
    JsonFormatter,
    configure_logging,
)
from taxflow.middleware.request_context import RequestIdFilter, request_id_var

SRC = Path(__file__).resolve().parent.parent / "src" / "taxflow"


def _format_record(**kwargs) -> dict:
    """Build a LogRecord, run it through the filter + JSON formatter, parse it."""
    record = logging.LogRecord(
        name="taxflow.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    for key, value in kwargs.items():
        setattr(record, key, value)
    RequestIdFilter().filter(record)
    return json.loads(JsonFormatter().format(record))


def test_formatter_emits_parseable_json_with_request_id():
    token = request_id_var.set("req-abc")
    try:
        payload = _format_record()
    finally:
        request_id_var.reset(token)

    assert payload["level"] == "INFO"
    assert payload["logger"] == "taxflow.test"
    assert payload["message"] == "hello world"
    assert payload["request_id"] == "req-abc"
    assert "timestamp" in payload


def test_formatter_default_request_id_is_dash():
    payload = _format_record()
    assert payload["request_id"] == "-"


def test_formatter_includes_extra_fields():
    payload = _format_record(method="GET", status_code=200, client_id="c-1")
    assert payload["method"] == "GET"
    assert payload["status_code"] == 200
    assert payload["client_id"] == "c-1"


def test_formatter_serialises_non_serialisable_extra_with_default_str():
    class Weird:
        def __str__(self):
            return "weird-repr"

    payload = _format_record(obj=Weird())
    # default=str keeps the record serialisable rather than raising.
    assert payload["obj"] == "weird-repr"


def test_level_honours_log_level():
    with patch("taxflow.logging_config.settings") as mock_settings:
        mock_settings.LOG_LEVEL = "WARNING"
        configure_logging()
        assert logging.getLogger().level == logging.WARNING
    # restore default
    with patch("taxflow.logging_config.settings") as mock_settings:
        mock_settings.LOG_LEVEL = "INFO"
        configure_logging()
        assert logging.getLogger().level == logging.INFO


def _taxflow_handlers() -> list[logging.Handler]:
    return [
        h
        for h in logging.getLogger().handlers
        if getattr(h, _HANDLER_MARKER, False)
    ]


def test_handler_writes_to_stdout():
    with patch("taxflow.logging_config.settings") as mock_settings:
        mock_settings.LOG_LEVEL = "INFO"
        configure_logging()
    handlers = _taxflow_handlers()
    assert len(handlers) == 1
    assert handlers[0].stream is sys.stdout


def test_configure_logging_preserves_unrelated_handlers():
    root = logging.getLogger()
    sentinel = logging.NullHandler()
    root.addHandler(sentinel)
    try:
        with patch("taxflow.logging_config.settings") as mock_settings:
            mock_settings.LOG_LEVEL = "INFO"
            configure_logging()
            # calling twice must not stack duplicate taxflow handlers
            configure_logging()
        assert sentinel in root.handlers
        assert len(_taxflow_handlers()) == 1
    finally:
        root.removeHandler(sentinel)


def _access_records(caplog) -> list[logging.LogRecord]:
    return [
        r
        for r in caplog.records
        if r.name == "taxflow.middleware.request_logging" and r.getMessage() == "request"
    ]


def test_request_returns_request_id_and_one_access_record(client, caplog):
    with caplog.at_level(logging.INFO, logger="taxflow.middleware.request_logging"):
        response = client.get("/health")

    assert response.status_code == 200
    assert response.headers.get("X-Request-ID")

    records = _access_records(caplog)
    assert len(records) == 1
    record = records[0]
    assert record.method == "GET"
    assert record.path == "/health"
    assert record.status_code == 200
    assert isinstance(record.latency_ms, float)
    # unauthenticated route → no client_id set on request.state
    assert record.client_id is None


def test_passed_in_request_id_is_echoed_unchanged(client):
    response = client.get("/health", headers={"X-Request-ID": "my-fixed-id"})
    assert response.headers["X-Request-ID"] == "my-fixed-id"


def test_unhandled_exception_emits_one_access_record_with_status_500(caplog):
    from fastapi.testclient import TestClient

    from taxflow.main import app

    @app.get("/_boom_test_route")
    async def _boom():  # pragma: no cover - body raises before returning
        raise RuntimeError("boom")

    # raise_server_exceptions=False so the client returns the 500 instead of
    # re-raising, letting us inspect the emitted access record.
    boom_client = TestClient(app, raise_server_exceptions=False)
    try:
        with caplog.at_level(
            logging.INFO, logger="taxflow.middleware.request_logging"
        ):
            response = boom_client.get("/_boom_test_route")
    finally:
        app.router.routes = [
            r
            for r in app.router.routes
            if getattr(r, "path", None) != "/_boom_test_route"
        ]

    assert response.status_code == 500
    records = _access_records(caplog)
    assert len(records) == 1
    assert records[0].status_code == 500
    assert records[0].path == "/_boom_test_route"


def test_authenticated_access_record_includes_client_id(client, caplog):
    """An authenticated route runs the real get_current_client, which sets
    request.state.client_id; the middleware must surface it on the access record.
    """
    from taxflow.db import get_db
    from taxflow.main import app

    identity = MagicMock(email="firm@example.com.au", metadata={})
    auth_port = MagicMock()
    auth_port.validate_token.return_value = identity

    mock_db = MagicMock()
    mock_db.notifications.list_for_client.return_value = []
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with patch(
            "taxflow.middleware.auth.providers.get_auth_port", return_value=auth_port
        ), patch(
            "taxflow.middleware.auth._get_or_provision_client",
            return_value={"id": "client-xyz"},
        ):
            with caplog.at_level(
                logging.INFO, logger="taxflow.middleware.request_logging"
            ):
                response = client.get(
                    "/notifications", headers={"Authorization": "Bearer tok"}
                )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200

    records = _access_records(caplog)
    assert len(records) == 1
    assert records[0].client_id == "client-xyz"


def test_no_print_in_src_except_cli_entrypoint():
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        for i, line in enumerate(path.read_text().splitlines(), start=1):
            if "print(" not in line:
                continue
            rel = path.relative_to(SRC).as_posix()
            # The knowledge ingest CLI __main__ entrypoint keeps its stdout print.
            if rel == "services/knowledge/ingest.py":
                continue
            offenders.append(f"{rel}:{i}")
    assert not offenders, f"Unexpected print() calls: {offenders}"
