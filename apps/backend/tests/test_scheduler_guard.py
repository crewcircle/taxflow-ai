"""Tests for the APScheduler multi-worker advisory-lock leader guard (Task B7).

Production runs 2 uvicorn workers, each with its own scheduler. The guard makes
only the worker that wins a Postgres advisory lock run each cron job; the others
skip. These tests patch the dedicated advisory-lock connection
(``psycopg2.connect`` where the adapter uses it) and assert:

* lock unavailable (``pg_try_advisory_lock`` -> False): the wrapped job body is
  NOT called, and the connection is still closed.
* lock acquired (True): the job body runs, and ``pg_advisory_unlock`` + the
  connection's ``close()`` are called even when the job body raises.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from taxflow.adapters.scheduler import apscheduler as adapter_mod


def _make_fake_conn(lock_acquired: bool) -> MagicMock:
    """Build a MagicMock psycopg2 connection whose cursor returns ``lock_acquired``.

    ``pg_try_advisory_lock`` is the first fetchone() call; it returns a 1-tuple
    ``(lock_acquired,)``.
    """
    conn = MagicMock(name="conn")
    cursor = MagicMock(name="cursor")
    cursor.fetchone.return_value = (lock_acquired,)
    # `with conn.cursor() as cur:` -> context manager yielding the cursor.
    ctx = MagicMock(name="cursor_ctx")
    ctx.__enter__.return_value = cursor
    ctx.__exit__.return_value = False
    conn.cursor.return_value = ctx
    return conn


def _executed_sql(conn: MagicMock) -> list[str]:
    """Return every SQL string passed to any cursor.execute on ``conn``."""
    cursor = conn.cursor.return_value.__enter__.return_value
    return [call.args[0] for call in cursor.execute.call_args_list]


def test_lock_unavailable_skips_job_body(monkeypatch):
    conn = _make_fake_conn(lock_acquired=False)
    monkeypatch.setattr(adapter_mod.psycopg2, "connect", lambda *a, **k: conn)

    body = MagicMock(name="job_body")
    guarded = adapter_mod._leader_guard("kb_ingestion", body)

    result = asyncio.run(guarded())

    assert result is None
    body.assert_not_called()
    # Only the try-lock ran; no unlock because we never acquired it.
    sqls = _executed_sql(conn)
    assert any("pg_try_advisory_lock" in s for s in sqls)
    assert not any("pg_advisory_unlock" in s for s in sqls)
    # Dedicated connection is always closed.
    conn.close.assert_called_once()


def test_lock_acquired_runs_job_and_unlocks(monkeypatch):
    conn = _make_fake_conn(lock_acquired=True)
    monkeypatch.setattr(adapter_mod.psycopg2, "connect", lambda *a, **k: conn)

    body = MagicMock(name="job_body")
    guarded = adapter_mod._leader_guard("demo_reset", body)

    asyncio.run(guarded())

    body.assert_called_once()
    sqls = _executed_sql(conn)
    assert any("pg_try_advisory_lock" in s for s in sqls)
    assert any("pg_advisory_unlock" in s for s in sqls)
    conn.close.assert_called_once()


def test_unlock_and_close_happen_even_when_job_raises(monkeypatch):
    conn = _make_fake_conn(lock_acquired=True)
    monkeypatch.setattr(adapter_mod.psycopg2, "connect", lambda *a, **k: conn)

    def boom():
        raise RuntimeError("job blew up")

    guarded = adapter_mod._leader_guard("regulatory_monitor", boom)

    with pytest.raises(RuntimeError, match="job blew up"):
        asyncio.run(guarded())

    sqls = _executed_sql(conn)
    assert any("pg_advisory_unlock" in s for s in sqls)
    conn.close.assert_called_once()


def test_async_job_body_is_awaited(monkeypatch):
    """Async job callables (the real jobs are coroutines) are awaited under the guard."""
    conn = _make_fake_conn(lock_acquired=True)
    monkeypatch.setattr(adapter_mod.psycopg2, "connect", lambda *a, **k: conn)

    calls: list[str] = []

    async def async_body():
        calls.append("ran")

    guarded = adapter_mod._leader_guard("kb_ingestion", async_body)
    asyncio.run(guarded())

    assert calls == ["ran"]
    conn.close.assert_called_once()


def test_distinct_lock_keys_per_job():
    keys = adapter_mod._LOCK_KEYS
    assert set(keys) == {"kb_ingestion", "regulatory_monitor", "demo_reset"}
    assert len(set(keys.values())) == 3
