"""Task C1: unit tests for the re_research_jobs + notifications repositories.

Follows the fake-cursor pattern of ``test_repositories.py``: a fake
``get_pg_conn()`` context manager records every executed SQL string + params,
so the tests assert repo behaviour + SQL shape without touching a real DB.
"""
from contextlib import contextmanager
from unittest.mock import patch

from taxflow.adapters.db import repositories
from taxflow.adapters.db.repositories import Repositories


class _FakeCursor:
    def __init__(self, fetchone=None, fetchall=None, rowcount=0):
        self.executed = []  # list of (sql, params)
        self._fetchone = fetchone
        self._fetchall = fetchall or []
        self.rowcount = rowcount

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return self._fetchone() if callable(self._fetchone) else self._fetchone

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
    conn = _FakeConn(cursor)
    yield conn


def _patch_conn(cursor):
    return patch.object(repositories, "get_pg_conn", lambda: _fake_pool(cursor))


def _all_sql(cursor) -> str:
    return "\n".join(sql for sql, _ in cursor.executed)


# --- enqueue: at-most-once via ON CONFLICT (feedback_id) DO NOTHING -----------


def test_enqueue_uses_on_conflict_do_nothing_on_feedback_id():
    cur = _FakeCursor(fetchone={"id": "job-1"})
    with _patch_conn(cur):
        Repositories().re_research_jobs.enqueue(
            {
                "client_id": "client-1",
                "query_id": "q1",
                "feedback_id": "fb1",
                "feedback_note": "The FBT rate is wrong",
                "original_answer": "old answer",
            }
        )
    sql, params = cur.executed[0]
    assert "INSERT INTO re_research_jobs" in sql
    assert "ON CONFLICT (feedback_id) DO NOTHING" in sql
    assert "RETURNING *" in sql
    # feedback_note is snapshotted at enqueue.
    assert "The FBT rate is wrong" in params


def test_enqueue_returns_none_on_duplicate_feedback_id():
    # ON CONFLICT DO NOTHING -> no RETURNING row -> fetchone() is None.
    cur = _FakeCursor(fetchone=None)
    with _patch_conn(cur):
        result = Repositories().re_research_jobs.enqueue(
            {"client_id": "c1", "query_id": "q1", "feedback_id": "dup-fb"}
        )
    assert result is None


# --- claim_next: atomic claim that sets running state ------------------------


def test_claim_next_sets_running_increments_attempts_and_uses_skip_locked():
    cur = _FakeCursor(
        fetchone={"id": "job-1", "status": "running", "attempts": 1}
    )
    with _patch_conn(cur):
        job = Repositories().re_research_jobs.claim_next()
    sql, _ = cur.executed[0]
    assert "UPDATE re_research_jobs" in sql
    assert "status = 'running'" in sql
    assert "attempts = attempts + 1" in sql
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "next_attempt_at <= now()" in sql
    assert "status = 'queued'" in sql
    assert job["status"] == "running"
    assert job["attempts"] == 1


def test_claim_next_returns_none_when_no_due_job():
    cur = _FakeCursor(fetchone=None)
    with _patch_conn(cur):
        assert Repositories().re_research_jobs.claim_next() is None


# --- requeue: transient failure resets to queued with future next_attempt ----


def test_requeue_resets_to_queued_with_future_next_attempt_and_backoff():
    cur = _FakeCursor()
    with _patch_conn(cur):
        Repositories().re_research_jobs.requeue("job-1", "timeout", 120)
    sql, params = cur.executed[0]
    assert "UPDATE re_research_jobs" in sql
    assert "status = 'queued'" in sql
    assert "next_attempt_at = now() + make_interval(secs => %s)" in sql
    assert "error_message = %s" in sql
    # error, backoff_seconds, job_id ordering.
    assert params == ("timeout", 120, "job-1")


# --- mark: terminal done/failed ----------------------------------------------


def test_mark_sets_terminal_status_and_extra_fields():
    cur = _FakeCursor()
    with _patch_conn(cur):
        Repositories().re_research_jobs.mark(
            "job-1", "failed", {"error_message": "boom"}
        )
    sql, params = cur.executed[0]
    assert "UPDATE re_research_jobs" in sql
    assert "status = %s" in sql
    assert "error_message = %s" in sql
    assert "WHERE id = %s" in sql
    assert params[0] == "failed"
    assert "boom" in params
    assert params[-1] == "job-1"


def test_mark_done_without_extra_fields():
    cur = _FakeCursor()
    with _patch_conn(cur):
        Repositories().re_research_jobs.mark("job-1", "done")
    sql, params = cur.executed[0]
    assert "status = %s" in sql
    assert params[0] == "done"
    assert params[-1] == "job-1"


# --- notifications: scoped by client_id --------------------------------------


def test_notifications_insert_targets_table():
    cur = _FakeCursor(fetchone={"id": "n1"})
    with _patch_conn(cur):
        Repositories().notifications.insert(
            {
                "client_id": "client-1",
                "kind": "answer_improved",
                "query_id": "q1",
                "title": "Answer updated",
                "body": "We re-researched your question.",
            }
        )
    assert "INSERT INTO notifications" in _all_sql(cur)


def test_notifications_list_for_client_scoped_by_client():
    cur = _FakeCursor(fetchall=[])
    with _patch_conn(cur):
        Repositories().notifications.list_for_client("client-1")
    sql, params = cur.executed[0]
    assert "FROM notifications" in sql
    assert "WHERE client_id = %s" in sql
    assert params[0] == "client-1"


def test_notifications_mark_read_scoped_by_id_and_client():
    cur = _FakeCursor()
    with _patch_conn(cur):
        Repositories().notifications.mark_read("client-1", "n1")
    sql, params = cur.executed[0]
    assert "UPDATE notifications" in sql
    assert "read_at = now()" in sql
    assert "WHERE id = %s AND client_id = %s" in sql
    assert params == ("n1", "client-1")


# --- QueriesRepo extensions --------------------------------------------------


def test_list_recent_selects_re_research_status():
    cur = _FakeCursor(fetchall=[])
    with _patch_conn(cur):
        Repositories().queries.list_recent("client-1", 50)
    sql, _ = cur.executed[0]
    assert "re_research_status" in sql
    assert "FROM queries" in sql


def test_set_re_research_status_scoped_by_client():
    cur = _FakeCursor()
    with _patch_conn(cur):
        Repositories().queries.set_re_research_status("client-1", "q1", "pending")
    sql, params = cur.executed[0]
    assert "UPDATE queries SET re_research_status = %s" in sql
    assert "WHERE id = %s AND client_id = %s" in sql
    assert params == ("pending", "q1", "client-1")


def test_get_answer_for_client_scoped_by_id_and_client():
    cur = _FakeCursor(
        fetchone={
            "question": "q",
            "final_answer": "a",
            "citations": [],
            "session_id": "s1",
            "client_ref": "ACME",
        }
    )
    with _patch_conn(cur):
        Repositories().queries.get_answer_for_client("client-1", "q1")
    sql, params = cur.executed[0]
    assert "FROM queries" in sql
    assert "id = %s AND client_id = %s" in sql
    assert params == ("q1", "client-1")


# --- facade wiring -----------------------------------------------------------


def test_repositories_exposes_new_aggregates():
    repos = Repositories()
    assert hasattr(repos, "re_research_jobs")
    assert hasattr(repos, "notifications")
