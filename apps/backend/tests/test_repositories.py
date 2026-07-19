"""Task B4: unit tests for the psycopg2 repositories.

These assert the SQL each repo emits (table name + a ``client_id`` predicate
where the aggregate is client-scoped) and a couple of behavioural contracts:
``trials.increment_usage`` calls the ``increment_trial_usage`` SQL function, and
``queries.get_question_citations`` is scoped by BOTH id AND client_id so one
client cannot read another client's query.

We drive a fake ``get_pg_conn()`` context manager that records every executed
SQL string + params, so the tests never touch a real database.
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
    """Patch get_pg_conn in the repositories module to yield our fake conn."""
    return patch.object(repositories, "get_pg_conn", lambda: _fake_pool(cursor))


def _all_sql(cursor) -> str:
    return "\n".join(sql for sql, _ in cursor.executed)


# --- client-scoped predicate presence ----------------------------------------


def test_queries_list_recent_scoped_by_client():
    cur = _FakeCursor(fetchall=[])
    with _patch_conn(cur):
        Repositories().queries.list_recent("client-1", 50)
    sql, params = cur.executed[0]
    assert "FROM queries" in sql
    assert "WHERE client_id = %s" in sql
    assert params[0] == "client-1"


def test_queries_get_for_client_scoped_by_client():
    cur = _FakeCursor(fetchone={"id": "q1", "client_id": "client-1"})
    with _patch_conn(cur):
        Repositories().queries.get_for_client("client-1", "q1")
    sql, params = cur.executed[0]
    assert "FROM queries" in sql
    assert "client_id = %s" in sql
    assert "client-1" in params


def test_documents_list_for_client_scoped_by_client():
    cur = _FakeCursor(fetchall=[])
    with _patch_conn(cur):
        Repositories().documents.list_for_client("client-1")
    sql, params = cur.executed[0]
    assert "FROM documents" in sql
    assert "WHERE client_id = %s" in sql
    assert params[0] == "client-1"


def test_documents_list_for_client_with_kind_filter_scoped_by_client():
    cur = _FakeCursor(fetchall=[])
    with _patch_conn(cur):
        Repositories().documents.list_for_client("client-1", "ato_response")
    sql, params = cur.executed[0]
    assert "FROM documents" in sql
    assert "client_id = %s" in sql
    assert "document_type = %s" in sql
    assert params == ("client-1", "ato_response")


def test_documents_get_for_client_scoped_by_client():
    cur = _FakeCursor(fetchone={"id": "d1", "client_id": "client-1"})
    with _patch_conn(cur):
        Repositories().documents.get_for_client("client-1", "d1")
    sql, params = cur.executed[0]
    assert "FROM documents" in sql
    assert "client_id = %s" in sql


def test_queries_update_scoped_by_client():
    cur = _FakeCursor()
    with _patch_conn(cur):
        Repositories().queries.update("client-1", "q1", {"status": "done"})
    sql, params = cur.executed[0]
    assert "UPDATE queries" in sql
    assert "WHERE id = %s AND client_id = %s" in sql
    assert list(params[-2:]) == ["q1", "client-1"]


def test_documents_update_status_scoped_by_client():
    cur = _FakeCursor()
    with _patch_conn(cur):
        Repositories().documents.update_status(
            "client-1", "d1", "approved", {"approved_at": "now()"}
        )
    sql, params = cur.executed[0]
    assert "UPDATE documents" in sql
    assert "WHERE id = %s AND client_id = %s" in sql
    assert list(params[-2:]) == ["d1", "client-1"]


def test_firm_knowledge_list_for_client_scoped_by_client():
    cur = _FakeCursor(fetchall=[])
    with _patch_conn(cur):
        Repositories().firm_knowledge.list_for_client("client-1")
    sql, params = cur.executed[0]
    assert "FROM firm_knowledge" in sql
    assert "WHERE client_id = %s" in sql
    assert params[0] == "client-1"


def test_firm_knowledge_delete_scoped_by_client():
    cur = _FakeCursor()
    with _patch_conn(cur):
        Repositories().firm_knowledge.delete("client-1", "fk1")
    sql, params = cur.executed[0]
    assert "DELETE FROM firm_knowledge" in sql
    assert "client_id = %s" in sql
    assert "client-1" in params


def test_trials_latest_for_client_scoped_by_client():
    cur = _FakeCursor(fetchone=None)
    with _patch_conn(cur):
        Repositories().trials.latest_for_client("client-1")
    sql, params = cur.executed[0]
    assert "FROM trials" in sql
    assert "WHERE client_id = %s" in sql
    assert params[0] == "client-1"


def test_query_cache_get_cached_scoped_by_client():
    cur = _FakeCursor(fetchone=None)
    with _patch_conn(cur):
        Repositories().query_cache.get_cached("q norm", "client-1", 3)
    sql, params = cur.executed[0]
    assert "FROM query_cache" in sql
    assert "client_id = %s" in sql
    assert "client-1" in params


def test_rate_limit_count_hits_scoped_by_client():
    cur = _FakeCursor(fetchone=[0])
    with _patch_conn(cur):
        Repositories().rate_limit.count_hits("client-1", 60)
    sql, params = cur.executed[0]
    assert "FROM rate_limit_hits" in sql
    assert "client_id = %s" in sql
    assert params[0] == "client-1"


# --- table-name presence for non-client-scoped repos -------------------------


def test_regulatory_alerts_list_recent_targets_table():
    cur = _FakeCursor(fetchall=[])
    with _patch_conn(cur):
        Repositories().regulatory_alerts.list_recent(50)
    assert "FROM regulatory_alerts" in _all_sql(cur)


def test_contact_insert_targets_table():
    cur = _FakeCursor(fetchone={"id": "c1"})
    with _patch_conn(cur):
        Repositories().contact.insert({"name": "n", "email": "e", "message": "m"})
    assert "INSERT INTO contact_messages" in _all_sql(cur)


def test_health_ping_selects_one():
    cur = _FakeCursor(fetchone=[1])
    with _patch_conn(cur):
        assert Repositories().health.ping() is True
    assert "SELECT 1" in _all_sql(cur)


def test_clients_get_by_email_targets_table():
    cur = _FakeCursor(fetchone=None)
    with _patch_conn(cur):
        Repositories().clients.get_by_email("a@b.com")
    assert "FROM clients" in _all_sql(cur)


# --- increment_usage uses the SQL function ------------------------------------


def test_increment_usage_calls_sql_function():
    cur = _FakeCursor()
    with _patch_conn(cur):
        Repositories().trials.increment_usage("client-1", "queries")
    sql, params = cur.executed[0]
    assert sql == "SELECT increment_trial_usage(%s, %s)"
    assert params == ("client-1", "queries")


# --- cross-client isolation for get_question_citations ------------------------


def test_get_question_citations_scoped_by_id_and_client():
    cur = _FakeCursor(fetchone={"question": "q", "citations": []})
    with _patch_conn(cur):
        Repositories().queries.get_question_citations("client-1", "query-1")
    sql, params = cur.executed[0]
    assert "FROM queries" in sql
    assert "id = %s AND client_id = %s" in sql
    # Ordered (query_id, client_id).
    assert params == ("query-1", "client-1")


def test_get_question_citations_returns_none_for_another_clients_query():
    # The row belongs to another client -> the id + client_id predicate matches
    # nothing, so fetchone() returns None and the repo returns None. One client
    # can never read/probe another client's query via this path.
    cur = _FakeCursor(fetchone=None)
    with _patch_conn(cur):
        result = Repositories().queries.get_question_citations("client-1", "other-clients-query")
    assert result is None


# --- firm_knowledge.usage_trend (Task C6) -------------------------------------


def test_firm_knowledge_usage_trend_scoped_by_client_and_quarter():
    cur = _FakeCursor(fetchone={"quarter_count": 4, "prior_count": 1})
    with _patch_conn(cur):
        trend = Repositories().firm_knowledge.usage_trend("client-1")

    sql, params = cur.executed[0]
    assert "FROM firm_knowledge" in sql
    assert "WHERE client_id = %s" in sql
    # This-quarter vs prior-quarter windows keyed off date_trunc('quarter', now()).
    assert "date_trunc('quarter', now())" in sql
    assert params == ("client-1",)
    assert trend == {"quarter_count": 4, "prior_count": 1}


def test_firm_knowledge_usage_trend_defaults_to_zero_when_no_rows():
    cur = _FakeCursor(fetchone=None)
    with _patch_conn(cur):
        trend = Repositories().firm_knowledge.usage_trend("client-1")
    assert trend == {"quarter_count": 0, "prior_count": 0}


# --- knowledge ingest short-circuits on empty input ---------------------------


def test_mark_superseded_empty_returns_zero_without_query():
    cur = _FakeCursor()
    with _patch_conn(cur):
        assert Repositories().knowledge_ingest.mark_superseded({}) == 0
    assert cur.executed == []


def test_mark_superseded_updates_superseded_by_with_unnest_and_parallel_arrays():
    cur = _FakeCursor(rowcount=2)
    mapping = {"TR 2020/4": "TR 2024/1", "TD 2019/1": "TR 2024/1"}
    with _patch_conn(cur):
        count = Repositories().knowledge_ingest.mark_superseded(mapping)

    assert count == 2
    assert len(cur.executed) == 1
    sql, params = cur.executed[0]
    assert "UPDATE knowledge_chunks" in sql
    assert "superseded_by" in sql
    assert "is_current = false" in sql
    assert "unnest(%s::text[], %s::text[])" in sql
    # two parallel arrays: old citations then new (superseding) citations,
    # aligned by index.
    old_arr, new_arr = params
    assert old_arr == list(mapping.keys())
    assert new_arr == [mapping[old] for old in old_arr]


def test_stale_urls_empty_returns_empty_without_query():
    cur = _FakeCursor()
    with _patch_conn(cur):
        assert Repositories().knowledge_ingest.stale_urls([]) == []
    assert cur.executed == []


def test_stale_urls_returns_urls_not_recently_scraped():
    # Only "fresh-url" comes back as recently scraped; the other is stale.
    cur = _FakeCursor(fetchall=[("fresh-url",)])
    with _patch_conn(cur):
        stale = Repositories().knowledge_ingest.stale_urls(["fresh-url", "stale-url"])
    assert stale == ["stale-url"]


# --- facade wiring ------------------------------------------------------------


def test_repositories_exposes_all_aggregates():
    repos = Repositories()
    for attr in (
        "clients",
        "trials",
        "queries",
        "query_feedback",
        "documents",
        "firm_knowledge",
        "regulatory_alerts",
        "contact",
        "rate_limit",
        "query_cache",
        "knowledge_ingest",
        "demo_reset",
        "health",
    ):
        assert hasattr(repos, attr)
