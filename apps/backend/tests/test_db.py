"""Tests for the shared psycopg2 connection pool helper (Task A1)."""
from unittest.mock import MagicMock

import pytest

import taxflow.db as db


class _FakePool:
    """Minimal ThreadedConnectionPool stand-in that tracks borrow/return."""

    def __init__(self):
        self.conn = MagicMock()
        self.borrowed = 0
        self.returned = []

    def getconn(self):
        self.borrowed += 1
        return self.conn

    def putconn(self, conn):
        self.returned.append(conn)


@pytest.fixture
def fake_pool(monkeypatch):
    pool = _FakePool()
    monkeypatch.setattr(db, "_get_pool", lambda: pool)
    return pool


def test_get_pg_conn_borrows_and_returns(fake_pool):
    with db.get_pg_conn() as conn:
        assert conn is fake_pool.conn
    assert fake_pool.borrowed == 1
    assert fake_pool.returned == [fake_pool.conn]


def test_get_pg_conn_returns_connection_on_exception(fake_pool):
    with pytest.raises(ValueError):
        with db.get_pg_conn() as conn:
            assert conn is fake_pool.conn
            raise ValueError("boom")
    # Connection must still be returned to the pool even though the body raised.
    assert fake_pool.returned == [fake_pool.conn]


def test_get_pg_conn_rolls_back_before_returning(fake_pool):
    with db.get_pg_conn():
        pass
    fake_pool.conn.rollback.assert_called_once()


def test_get_pg_conn_returns_even_if_rollback_fails(fake_pool):
    fake_pool.conn.rollback.side_effect = RuntimeError("rollback failed")
    # A rollback failure must not prevent the connection from returning to the pool.
    with db.get_pg_conn():
        pass
    assert fake_pool.returned == [fake_pool.conn]
