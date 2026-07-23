"""Phase 2: one-time firm_client_id backfill (offline, no DB/LLM/network).

Mirrors test_backfill_engagements.py: repo-level SQL asserted against a fake
conn, orchestration asserted against a mock db.
"""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

# Make scripts/ importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import backfill_firm_client_ids  # noqa: E402

from taxflow.adapters.db import repositories  # noqa: E402
from taxflow.adapters.db.repositories import FirmClientBackfillRepo  # noqa: E402
from taxflow.routers._shared import (  # noqa: E402
    LIVE_UNATTRIBUTED_DESCRIPTION,
    UNATTRIBUTED_FIRM_CLIENT_NAME,
)


# --- fake conn (mirrors test_backfill_engagements.py) ------------------------
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


# --- repo SQL shape ------------------------------------------------------------


def test_link_via_engagement_joins_both_tables_idempotent():
    cur = _FakeCursor(rowcount=4)
    with _patch_conn(cur):
        linked = FirmClientBackfillRepo().link_via_engagement("client-1")
    assert len(cur.executed) == 2  # queries + documents
    for sql, params in cur.executed:
        assert "SET firm_client_id = e.firm_client_id" in sql
        assert "FROM engagements e" in sql
        assert "t.engagement_id = e.id" in sql
        assert "t.firm_client_id IS NULL" in sql  # idempotent guard
        assert "t.client_id = %s" in sql
        assert params == ("client-1",)
    assert linked == 8  # rowcount(4) per table x 2 tables


def test_link_via_engagement_all_tenants_when_no_client():
    cur = _FakeCursor(rowcount=1)
    with _patch_conn(cur):
        FirmClientBackfillRepo().link_via_engagement()
    for sql, params in cur.executed:
        assert params == ()
        assert "t.client_id = %s" not in sql


def test_distinct_fully_orphaned_clients_guards_both_columns():
    cur = _FakeCursor(fetchall=[])
    with _patch_conn(cur):
        FirmClientBackfillRepo().distinct_fully_orphaned_clients()
    sql, params = cur.executed[0]
    assert "firm_client_id IS NULL" in sql
    assert "engagement_id IS NULL" in sql
    assert "FROM queries" in sql
    assert "FROM documents" in sql


def test_link_orphans_to_engagement_scoped_and_idempotent():
    cur = _FakeCursor(rowcount=2)
    with _patch_conn(cur):
        linked = FirmClientBackfillRepo().link_orphans_to_engagement(
            "client-1", "eng-1", "fc-1"
        )
    assert len(cur.executed) == 2
    for sql, params in cur.executed:
        assert "SET firm_client_id = %s, engagement_id = %s" in sql
        assert "firm_client_id IS NULL AND engagement_id IS NULL" in sql
        assert params == ("fc-1", "eng-1", "client-1")
    assert linked == 4


# --- orchestration -------------------------------------------------------------


def _mock_db():
    db = MagicMock()
    db.firm_clients.create.side_effect = lambda cid, name: {"id": f"fc:{name}", "name": name}
    db.engagements.get_by_firm_client_and_description.return_value = None
    db.engagements.create.side_effect = lambda cid, fcid, desc: {"id": f"eng:{fcid}"}
    db.firm_client_backfill.link_orphans_to_engagement.return_value = 3
    return db


def test_resolve_orphan_client_creates_unattributed_bucket_and_links():
    db = _mock_db()
    backfill_firm_client_ids.resolve_orphan_client(db, "client-1", dry_run=False)
    db.firm_clients.create.assert_called_once_with("client-1", UNATTRIBUTED_FIRM_CLIENT_NAME)
    db.engagements.get_by_firm_client_and_description.assert_called_once_with(
        "client-1", "fc:" + UNATTRIBUTED_FIRM_CLIENT_NAME, LIVE_UNATTRIBUTED_DESCRIPTION
    )
    db.engagements.create.assert_called_once_with(
        "client-1", "fc:" + UNATTRIBUTED_FIRM_CLIENT_NAME, LIVE_UNATTRIBUTED_DESCRIPTION
    )
    db.firm_client_backfill.link_orphans_to_engagement.assert_called_once_with(
        "client-1", "eng:fc:" + UNATTRIBUTED_FIRM_CLIENT_NAME, "fc:" + UNATTRIBUTED_FIRM_CLIENT_NAME
    )


def test_resolve_orphan_client_reuses_existing_general_engagement():
    """Must not mint a second General engagement if one already exists."""
    db = _mock_db()
    db.engagements.get_by_firm_client_and_description.return_value = {"id": "eng-existing"}
    backfill_firm_client_ids.resolve_orphan_client(db, "client-1", dry_run=False)
    db.engagements.create.assert_not_called()
    db.firm_client_backfill.link_orphans_to_engagement.assert_called_once_with(
        "client-1", "eng-existing", "fc:" + UNATTRIBUTED_FIRM_CLIENT_NAME
    )


def test_resolve_orphan_client_dry_run_writes_nothing():
    db = _mock_db()
    backfill_firm_client_ids.resolve_orphan_client(db, "client-1", dry_run=True)
    db.firm_clients.create.assert_not_called()
    db.engagements.create.assert_not_called()
    db.firm_client_backfill.link_orphans_to_engagement.assert_not_called()


def test_run_backfill_links_via_engagement_then_resolves_orphans():
    db = _mock_db()
    db.firm_client_backfill.link_via_engagement.return_value = 42
    db.firm_client_backfill.distinct_fully_orphaned_clients.return_value = ["client-1", "client-2"]
    with patch.object(backfill_firm_client_ids, "get_relational_data", lambda: db):
        backfill_firm_client_ids.run_backfill(dry_run=False)
    db.firm_client_backfill.link_via_engagement.assert_called_once_with()
    assert db.firm_clients.create.call_count == 2


def test_run_backfill_dry_run_only_reads():
    db = _mock_db()
    db.firm_client_backfill.distinct_fully_orphaned_clients.return_value = ["client-1"]
    with patch.object(backfill_firm_client_ids, "get_relational_data", lambda: db):
        backfill_firm_client_ids.run_backfill(dry_run=True)
    db.firm_client_backfill.link_via_engagement.assert_not_called()
    db.firm_clients.create.assert_not_called()


def test_rerun_with_no_orphans_changes_nothing():
    db = _mock_db()
    db.firm_client_backfill.link_via_engagement.return_value = 0
    db.firm_client_backfill.distinct_fully_orphaned_clients.return_value = []
    with patch.object(backfill_firm_client_ids, "get_relational_data", lambda: db):
        backfill_firm_client_ids.run_backfill(dry_run=False)
    db.firm_clients.create.assert_not_called()
