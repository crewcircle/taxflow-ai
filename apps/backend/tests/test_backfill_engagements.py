"""Phase 2: one-time engagement backfill (offline, no DB/LLM/network).

Two layers, mirroring test_rechunk_backfill.py:
  - the ``EngagementBackfillRepo`` SQL is asserted against a fake conn (like
    test_repositories.py): client-scoped predicates + idempotent
    ``engagement_id IS NULL`` guard;
  - the orchestration (``backfill_bucket`` / ``run_backfill``) runs on a mock db
    and asserts the runtime create-path is used, the unattributed bucket maps to
    the synthetic firm-client, and a re-run (no buckets) changes nothing.
"""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

# Make scripts/ importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import backfill_engagements  # noqa: E402

from taxflow.adapters.db import repositories  # noqa: E402
from taxflow.adapters.db.repositories import EngagementBackfillRepo  # noqa: E402


# --- fake conn (mirrors test_repositories.py) --------------------------------
class _FakeCursor:
    def __init__(self, fetchall=None, rowcount=0):
        self.executed = []
        self._fetchall = fetchall or []
        self.rowcount = rowcount

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

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


# --- repo SQL shape ----------------------------------------------------------


def test_distinct_unlinked_buckets_scoped_and_guarded():
    cur = _FakeCursor(fetchall=[])
    with _patch_conn(cur):
        EngagementBackfillRepo().distinct_unlinked_buckets("client-1")
    sql, params = cur.executed[0]
    # Unions queries + documents, only unlinked rows, normalises client_ref.
    assert "FROM queries" in sql
    assert "FROM documents" in sql
    assert "engagement_id IS NULL" in sql
    assert "NULLIF(TRIM(client_ref), '')" in sql
    # Client-scoped when a client_id is supplied.
    assert "client_id = %s" in sql
    assert params == ["client-1", "client-1"]


def test_distinct_unlinked_buckets_all_tenants_when_no_client():
    cur = _FakeCursor(fetchall=[])
    with _patch_conn(cur):
        EngagementBackfillRepo().distinct_unlinked_buckets()
    sql, params = cur.executed[0]
    assert params == []
    # No per-tenant predicate, but still only unlinked rows.
    assert "engagement_id IS NULL" in sql


def test_link_bucket_named_ref_scoped_and_idempotent():
    cur = _FakeCursor(rowcount=3)
    with _patch_conn(cur):
        linked = EngagementBackfillRepo().link_bucket("client-1", "Acme", "eng-1")
    # One UPDATE per table (queries + documents).
    assert len(cur.executed) == 2
    for sql, params in cur.executed:
        assert "SET engagement_id = %s" in sql
        assert "client_id = %s" in sql
        assert "NULLIF(TRIM(client_ref), '') = %s" in sql
        assert "engagement_id IS NULL" in sql  # idempotent guard
        assert params == ("eng-1", "client-1", "Acme")
    assert linked == 6  # rowcount(3) per table x 2 tables


def test_link_bucket_null_ref_uses_is_null_predicate():
    cur = _FakeCursor(rowcount=2)
    with _patch_conn(cur):
        linked = EngagementBackfillRepo().link_bucket("client-1", None, "eng-u")
    assert len(cur.executed) == 2
    for sql, params in cur.executed:
        assert "NULLIF(TRIM(client_ref), '') IS NULL" in sql
        assert "engagement_id IS NULL" in sql
        assert params == ("eng-u", "client-1")
    assert linked == 4


# --- orchestration -----------------------------------------------------------


def _mock_db():
    db = MagicMock()
    db.firm_clients.create.side_effect = lambda cid, name: {"id": f"fc:{name}", "name": name}
    db.engagements.create.side_effect = lambda cid, fcid, desc, by=None: {
        "id": f"eng:{fcid}",
        "engagement_number": 1,
    }
    db.engagement_backfill.link_bucket.return_value = 5
    return db


def test_backfill_named_bucket_creates_client_and_engagement_and_links():
    db = _mock_db()
    backfill_engagements.backfill_bucket(
        db, {"client_id": "client-1", "client_ref": "Acme"}, dry_run=False
    )
    db.firm_clients.create.assert_called_once_with("client-1", "Acme")
    # Uses the runtime create path (advances next_engagement_seq).
    db.engagements.create.assert_called_once()
    args = db.engagements.create.call_args.args
    assert args[0] == "client-1"
    assert args[1] == "fc:Acme"
    db.engagement_backfill.link_bucket.assert_called_once_with(
        "client-1", "Acme", "eng:fc:Acme"
    )


def test_backfill_null_bucket_uses_synthetic_unattributed_client():
    db = _mock_db()
    backfill_engagements.backfill_bucket(
        db, {"client_id": "client-1", "client_ref": None}, dry_run=False
    )
    db.firm_clients.create.assert_called_once_with(
        "client-1", backfill_engagements.UNATTRIBUTED_NAME
    )
    db.engagement_backfill.link_bucket.assert_called_once_with(
        "client-1", None, f"eng:fc:{backfill_engagements.UNATTRIBUTED_NAME}"
    )


def test_backfill_dry_run_writes_nothing():
    db = _mock_db()
    backfill_engagements.backfill_bucket(
        db, {"client_id": "client-1", "client_ref": "Acme"}, dry_run=True
    )
    db.firm_clients.create.assert_not_called()
    db.engagements.create.assert_not_called()
    db.engagement_backfill.link_bucket.assert_not_called()


def test_rerun_with_no_buckets_changes_nothing():
    db = _mock_db()
    db.engagement_backfill.distinct_unlinked_buckets.return_value = []
    with patch.object(backfill_engagements, "get_relational_data", lambda: db):
        backfill_engagements.run_backfill(client_id="client-1", dry_run=False)
    db.firm_clients.create.assert_not_called()
    db.engagements.create.assert_not_called()
    db.engagement_backfill.link_bucket.assert_not_called()


def test_run_backfill_processes_each_bucket_once():
    db = _mock_db()
    db.engagement_backfill.distinct_unlinked_buckets.return_value = [
        {"client_id": "client-1", "client_ref": "Acme"},
        {"client_id": "client-1", "client_ref": None},
    ]
    with patch.object(backfill_engagements, "get_relational_data", lambda: db):
        backfill_engagements.run_backfill(client_id="client-1", dry_run=False)
    assert db.engagements.create.call_count == 2
    assert db.engagement_backfill.link_bucket.call_count == 2
