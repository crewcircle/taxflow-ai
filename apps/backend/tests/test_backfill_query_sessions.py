"""Phase 3: query_sessions eager-creation + one-time backfill (offline, no
DB/LLM/network). Mirrors test_backfill_firm_client_ids.py's style.
"""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

# Make scripts/ importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import backfill_query_sessions  # noqa: E402

from taxflow.adapters.db import repositories  # noqa: E402
from taxflow.adapters.db.repositories import QuerySessionsRepo  # noqa: E402


# --- fake conn (mirrors test_backfill_firm_client_ids.py) --------------------
class _FakeCursor:
    def __init__(self, fetchall=None, rowcount=0):
        self.executed = []
        self._fetchall = fetchall or []
        self.rowcount = rowcount

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return None

    def fetchall(self):
        return self._fetchall

    def close(self):
        pass


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def cursor(self, *args, **kwargs):
        return self._cursor

    def commit(self):
        self.committed = True


@contextmanager
def _fake_pool(cursor):
    yield _FakeConn(cursor)


def _patch_conn(cursor):
    return patch.object(repositories, "get_pg_conn", lambda: _fake_pool(cursor))


# --- repo SQL shape ------------------------------------------------------------


def test_get_or_create_inserts_with_attribution_idempotent():
    cur = _FakeCursor()
    with _patch_conn(cur):
        QuerySessionsRepo().get_or_create("client-1", "sess-1", "eng-1", "fc-1")
    sql, params = cur.executed[0]
    assert "INSERT INTO query_sessions" in sql
    assert "ON CONFLICT (session_id) DO NOTHING" in sql
    assert params == ("sess-1", "client-1", "eng-1", "fc-1")


def test_distinct_sessions_missing_row_left_joins_and_filters_null():
    cur = _FakeCursor(fetchall=[])
    with _patch_conn(cur):
        QuerySessionsRepo().distinct_sessions_missing_row()
    sql, params = cur.executed[0]
    assert "LEFT JOIN query_sessions qs" in sql
    assert "qs.session_id IS NULL" in sql
    assert "q.session_id IS NOT NULL" in sql
    assert "DISTINCT ON (q.session_id)" in sql
    assert "ORDER BY q.session_id, q.created_at DESC" in sql


# --- backfill script orchestration ----------------------------------------------


def _mock_db():
    db = MagicMock()
    db.query_sessions.distinct_sessions_missing_row.return_value = [
        {"session_id": "sess-1", "client_id": "client-1", "engagement_id": "eng-1", "firm_client_id": "fc-1"},
        {"session_id": "sess-2", "client_id": "client-1", "engagement_id": None, "firm_client_id": None},
    ]
    return db


def test_run_backfill_creates_one_row_per_missing_session():
    db = _mock_db()
    with patch.object(backfill_query_sessions, "get_relational_data", lambda: db):
        backfill_query_sessions.run_backfill(dry_run=False)
    assert db.query_sessions.get_or_create.call_count == 2
    db.query_sessions.get_or_create.assert_any_call("client-1", "sess-1", "eng-1", "fc-1")
    db.query_sessions.get_or_create.assert_any_call("client-1", "sess-2", None, None)


def test_run_backfill_dry_run_writes_nothing():
    db = _mock_db()
    with patch.object(backfill_query_sessions, "get_relational_data", lambda: db):
        backfill_query_sessions.run_backfill(dry_run=True)
    db.query_sessions.get_or_create.assert_not_called()


def test_rerun_with_no_missing_sessions_changes_nothing():
    db = MagicMock()
    db.query_sessions.distinct_sessions_missing_row.return_value = []
    with patch.object(backfill_query_sessions, "get_relational_data", lambda: db):
        backfill_query_sessions.run_backfill(dry_run=False)
    db.query_sessions.get_or_create.assert_not_called()
