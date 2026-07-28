"""Tests for the shared psycopg2 connection pool helper (Task A1)."""
from unittest.mock import MagicMock

import pytest

import taxflow.db as db


class _FakePool:
    """Minimal ThreadedConnectionPool stand-in that tracks borrow/return."""

    def __init__(self):
        self.conn = MagicMock()
        self.conn.closed = False  # MagicMock().closed is truthy by default
        self.borrowed = 0
        self.returned = []  # list of (conn, close) tuples

    def getconn(self):
        self.borrowed += 1
        return self.conn

    def putconn(self, conn, close=False):
        self.returned.append((conn, close))


@pytest.fixture
def fake_pool(monkeypatch):
    pool = _FakePool()
    monkeypatch.setattr(db, "_get_pool", lambda: pool)
    return pool


def test_get_pg_conn_borrows_and_returns(fake_pool):
    with db.get_pg_conn() as conn:
        assert conn is fake_pool.conn
    assert fake_pool.borrowed == 1
    assert fake_pool.returned == [(fake_pool.conn, False)]


def test_get_pg_conn_returns_connection_on_exception(fake_pool):
    with pytest.raises(ValueError):
        with db.get_pg_conn() as conn:
            assert conn is fake_pool.conn
            raise ValueError("boom")
    # Connection must still be returned to the pool even though the body raised.
    assert fake_pool.returned == [(fake_pool.conn, False)]


def test_get_pg_conn_rolls_back_before_returning(fake_pool):
    with db.get_pg_conn():
        pass
    fake_pool.conn.rollback.assert_called_once()


def test_get_pg_conn_returns_even_if_rollback_fails(fake_pool):
    fake_pool.conn.rollback.side_effect = RuntimeError("rollback failed")
    # A rollback failure must not prevent the connection from returning to the pool.
    with db.get_pg_conn():
        pass
    assert fake_pool.returned == [(fake_pool.conn, False)]


# --- pre-ping: dead connections are discarded, not silently reused -----------
# Observed in production/experiment traffic: Supabase's pooler can silently
# drop a connection that's sat idle in our pool (e.g. during a long LLM call
# between DB calls). Reusing it as-is raises psycopg2.InterfaceError on the
# caller's first real query - a pre-ping SELECT 1 (or a `.closed` check)
# catches this before that happens.


class _DeadThenLiveConnPool:
    """Pool whose first getconn() returns a connection that LOOKS open
    (`.closed == False`) but fails on any query - simulating a connection the
    server has silently closed. The second getconn() returns a healthy one."""

    def __init__(self):
        self.dead_conn = MagicMock()
        self.dead_conn.closed = False
        self.dead_conn.cursor.side_effect = RuntimeError("connection already closed")
        self.live_conn = MagicMock()
        self.live_conn.closed = False
        self.getconn_calls = 0
        self.returned = []

    def getconn(self):
        self.getconn_calls += 1
        return self.dead_conn if self.getconn_calls == 1 else self.live_conn

    def putconn(self, conn, close=False):
        self.returned.append((conn, close))


def test_get_pg_conn_discards_dead_connection_and_retries(monkeypatch):
    pool = _DeadThenLiveConnPool()
    monkeypatch.setattr(db, "_get_pool", lambda: pool)

    with db.get_pg_conn() as conn:
        assert conn is pool.live_conn

    assert pool.getconn_calls == 2
    # The dead connection was discarded with close=True, never handed to the caller.
    assert (pool.dead_conn, True) in pool.returned
    assert (pool.live_conn, False) in pool.returned


def test_get_pg_conn_discards_connection_already_marked_closed(monkeypatch):
    """A connection whose own `.closed` flag is already truthy is discarded
    without even attempting the SELECT 1 probe."""
    pool = _DeadThenLiveConnPool()
    pool.dead_conn.closed = True
    monkeypatch.setattr(db, "_get_pool", lambda: pool)

    with db.get_pg_conn() as conn:
        assert conn is pool.live_conn

    pool.dead_conn.cursor.assert_not_called()
    assert (pool.dead_conn, True) in pool.returned


def test_get_pg_conn_does_not_probe_a_healthy_connection_twice(fake_pool):
    """The common case (healthy connection) should probe once and proceed -
    no discard, no extra getconn() call."""
    with db.get_pg_conn() as conn:
        assert conn is fake_pool.conn
    assert fake_pool.borrowed == 1
    fake_pool.conn.cursor.assert_called_once()
