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


# --- ops notifications (Task 3a-0) -------------------------------------------


def test_ops_notifications_insert_builds_insert_returning():
    cur = _FakeCursor(fetchone={"id": "n1", "kind": "drift"})
    with _patch_conn(cur):
        row = Repositories().ops_notifications.insert(
            {"kind": "drift", "title": "t", "body": "b", "severity": "warning"}
        )
    sql, params = cur.executed[0]
    assert "INSERT INTO ops_notifications" in sql
    assert "RETURNING *" in sql
    # Ops-scoped: no client_id anywhere in the write.
    assert "client_id" not in sql
    assert row == {"id": "n1", "kind": "drift"}


def test_ops_notifications_insert_serialises_jsonb_metadata():
    cur = _FakeCursor(fetchone={"id": "n1"})
    with _patch_conn(cur):
        Repositories().ops_notifications.insert(
            {"kind": "drift", "metadata": {"regressed": ["avg_confidence"]}}
        )
    _sql, params = cur.executed[0]
    # dict metadata is JSON-encoded for the jsonb column.
    assert '{"regressed": ["avg_confidence"]}' in params


def test_ops_notifications_latest_orders_created_at_desc():
    cur = _FakeCursor(fetchall=[])
    with _patch_conn(cur):
        Repositories().ops_notifications.latest(10)
    sql, params = cur.executed[0]
    assert "FROM ops_notifications" in sql
    assert "ORDER BY created_at DESC" in sql
    assert "client_id" not in sql
    assert params == (10,)


def test_ops_notifications_mark_read_updates_by_id():
    cur = _FakeCursor()
    with _patch_conn(cur):
        Repositories().ops_notifications.mark_read("n1")
    sql, params = cur.executed[0]
    assert "UPDATE ops_notifications SET read_at = now()" in sql
    assert "WHERE id = %s" in sql
    # No client_id predicate — the table is operator-global.
    assert "client_id" not in sql
    assert params == ("n1",)


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
        "notifications",
        "ops_notifications",
    ):
        assert hasattr(repos, attr)


# --- production snapshots (036) : operator-scoped, no client_id --------------


def test_production_snapshots_insert_targets_table():
    cur = _FakeCursor(fetchone={"id": "snap-1"})
    with _patch_conn(cur):
        Repositories().production_snapshots.insert(
            {
                "window_start": "2026-07-19T00:00:00Z",
                "window_end": "2026-07-20T00:00:00Z",
                "metrics": {"overall": {"avg_confidence": 0.8}},
                "diff": {"regressions": []},
                "has_regressions": False,
            }
        )
    sql, params = cur.executed[0]
    assert "INSERT INTO production_quality_snapshots" in sql
    assert "RETURNING *" in sql
    # jsonb columns are serialised to strings by _maybe_json.
    assert any(isinstance(p, str) and "avg_confidence" in p for p in params)


def test_production_snapshots_latest_orders_created_at_desc():
    cur = _FakeCursor(fetchall=[])
    with _patch_conn(cur):
        Repositories().production_snapshots.latest(5)
    sql, params = cur.executed[0]
    assert "FROM production_quality_snapshots" in sql
    assert "ORDER BY created_at DESC" in sql
    assert params == (5,)


def test_production_snapshots_baseline_window_uses_half_open_range():
    cur = _FakeCursor(fetchall=[])
    with _patch_conn(cur):
        Repositories().production_snapshots.baseline_window("2026-07-01", "2026-07-08")
    sql, params = cur.executed[0]
    assert "FROM production_quality_snapshots" in sql
    # explicit [start, end) window: lower bound inclusive, upper exclusive.
    assert "created_at >= %s AND created_at < %s" in sql
    assert params == ("2026-07-01", "2026-07-08")
# --- QueriesRepo.stats (Task 2b) ---------------------------------------------
#
# stats() runs several statements (the 035-column probe, the totals CTE, and the
# breakdown/by_model/by_day GROUP BYs). We drive a routing fake cursor that maps
# each executed SQL to a canned result and records every (sql, params) pair so
# the tests can assert both the SQL shape and the returned aggregate.


from datetime import datetime, timezone


class _RoutingCursor:
    """Fake cursor whose fetchone/fetchall answers depend on the SQL just run.

    ``present_columns`` controls which migration-035 columns the probe reports.
    """

    def __init__(self, present_columns=("cost_usd", "citation_valid", "model_id"),
                 totals=None, breakdown=None, by_model=None, by_day=None):
        self.executed = []  # (sql, params)
        self._present = list(present_columns)
        self._totals = totals or {}
        self._breakdown = breakdown or []
        self._by_model = by_model or []
        self._by_day = by_day or []
        self._last_sql = ""

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        self._last_sql = sql

    def fetchone(self):
        # The 035-column probe uses a plain cursor + fetchall (_fetchcol), so the
        # only fetchone path is the totals CTE.
        return dict(self._totals)

    def fetchall(self):
        sql = self._last_sql
        if "information_schema.columns" in sql:
            return [(c,) for c in self._present]
        if "GROUP BY verification_result" in sql:
            return [dict(r) for r in self._breakdown]
        if "GROUP BY model_used" in sql:
            return [dict(r) for r in self._by_model]
        if "date_trunc('day'" in sql:
            return [dict(r) for r in self._by_day]
        return []

    def close(self):
        pass


def _stats_sql(cursor) -> str:
    return "\n".join(sql for sql, _ in cursor.executed)


def _run_stats(cur, **kwargs):
    with _patch_conn(cur):
        return Repositories().queries.stats(**kwargs)


def test_stats_window_lower_bound_only_when_end_none():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    cur = _RoutingCursor()
    _run_stats(cur, start=start)
    sql = _stats_sql(cur)
    assert "created_at >= %(start)s" in sql
    # Upper bound predicate is present but guarded on a NULL end.
    assert "%(end)s::timestamptz IS NULL OR created_at < %(end)s" in sql
    # end passed as None for every statement.
    for _, params in cur.executed:
        if params and "start" in params:
            assert params["start"] == start
            assert params["end"] is None


def test_stats_window_includes_both_bounds_when_end_given():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 8, tzinfo=timezone.utc)
    cur = _RoutingCursor()
    _run_stats(cur, start=start, end=end)
    sql = _stats_sql(cur)
    assert "created_at >= %(start)s" in sql
    assert "created_at < %(end)s" in sql
    # Both bounds carried in params for the aggregate statements.
    saw_window = False
    for stmt_sql, params in cur.executed:
        if params and "start" in params:
            saw_window = True
            assert params["start"] == start
            assert params["end"] == end
    assert saw_window


def test_stats_excludes_cache_from_means_via_filter():
    cur = _RoutingCursor()
    _run_stats(cur, start=datetime(2026, 1, 1, tzinfo=timezone.utc))
    sql = _stats_sql(cur)
    # Cost/latency/quality means exclude cache via a FILTER, not a WHERE.
    assert "model_used <> 'cache'" in sql
    assert "FILTER (WHERE model_used <> 'cache')" in sql


def test_stats_has_by_model_and_by_day_group_bys():
    cur = _RoutingCursor()
    _run_stats(cur, start=datetime(2026, 1, 1, tzinfo=timezone.utc))
    sql = _stats_sql(cur)
    assert "GROUP BY model_used" in sql
    assert "date_trunc('day', created_at)" in sql
    assert "GROUP BY date_trunc('day', created_at)" in sql
    # verification breakdown groups on overall_status.
    assert "verification_result->>'overall_status'" in sql
    assert "GROUP BY verification_result->>'overall_status'" in sql


def test_stats_by_model_averages_exclude_cache_via_filter():
    cur = _RoutingCursor()
    _run_stats(cur, start=datetime(2026, 1, 1, tzinfo=timezone.utc))
    # The by_model breakdown keeps cache in count(*) but excludes it from the
    # mean metrics, so the 'cache' group's averages never leak into the rows.
    by_model_sql = next(
        sql for sql, _ in cur.executed if "GROUP BY model_used" in sql
    )
    assert "avg(wall_time_ms) FILTER (WHERE model_used <> 'cache')" in by_model_sql
    assert "avg(confidence_score) FILTER (WHERE model_used <> 'cache')" in by_model_sql
    assert "avg(cost_usd) FILTER (WHERE model_used <> 'cache')" in by_model_sql
    # But the per-model volume/count still includes cache rows.
    assert "count(*) AS query_volume" in by_model_sql


def test_stats_feedback_computed_in_separate_cte_not_joined():
    cur = _RoutingCursor()
    _run_stats(cur, start=datetime(2026, 1, 1, tzinfo=timezone.utc))
    sql = _stats_sql(cur)
    # Feedback lives in its own CTE cross-joined to the query aggregate -- never
    # LEFT JOINed into the per-query rows (which would multiply query rows).
    assert "feedback AS (" in sql
    assert "CROSS JOIN feedback" in sql
    assert "LEFT JOIN query_feedback" not in sql
    assert "JOIN query_feedback" not in sql


def test_stats_two_feedback_rows_do_not_double_count_volume_or_averages():
    # The DB does the aggregation; the contract we prove here is that feedback
    # counts come from the SEPARATE feedback CTE and never inflate the query
    # totals. Totals report 3 queries with avg latency 100 regardless of there
    # being 2 feedback rows (1 up + 1 down) attached to a single query.
    totals = {
        "query_volume": 3,
        "avg_latency_ms": 100.0,
        "p95_latency_ms": 180.0,
        "avg_confidence": 0.8,
        "verification_failures": 0,
        "non_cache_verified": 2,
        "total_cost_usd": 0.06,
        "avg_cost_usd": 0.02,
        "citation_valid_true": 2,
        "citation_valid_nonnull": 2,
        "feedback_up": 1,
        "feedback_down": 1,
    }
    cur = _RoutingCursor(totals=totals)
    result = _run_stats(cur, start=datetime(2026, 1, 1, tzinfo=timezone.utc))
    # Volume + averages come straight from the query CTE (feedback not joined).
    assert result["query_volume"] == 3
    assert result["avg_latency_ms"] == 100.0
    assert result["p95_latency_ms"] == 180.0
    assert result["feedback_up"] == 1
    assert result["feedback_down"] == 1
    assert result["feedback_up_rate"] == 0.5
    assert result["feedback_down_rate"] == 0.5


def test_stats_rate_denominators_and_breakdown():
    totals = {
        "query_volume": 10,
        "avg_latency_ms": 120.0,
        "p95_latency_ms": 200.0,
        "avg_confidence": 0.75,
        "verification_failures": 3,  # needs_correction + unreliable + parse_error
        "non_cache_verified": 6,
        "total_cost_usd": 1.2,
        "avg_cost_usd": 0.15,
        "citation_valid_true": 4,
        "citation_valid_nonnull": 5,
        "feedback_up": 3,
        "feedback_down": 1,
    }
    breakdown = [
        {"overall_status": "verified", "count": 4},
        {"overall_status": "needs_correction", "count": 2},
    ]
    cur = _RoutingCursor(totals=totals, breakdown=breakdown)
    result = _run_stats(cur, start=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert result["verification_failure_rate"] == 3 / 6
    assert result["citation_validity_rate"] == 4 / 5
    assert result["feedback_up_rate"] == 3 / 4
    assert result["feedback_down_rate"] == 1 / 4
    assert result["verification_breakdown"] == {"verified": 4, "needs_correction": 2}


def test_stats_rates_null_on_zero_denominators():
    totals = {
        "query_volume": 0,
        "avg_latency_ms": None,
        "p95_latency_ms": None,
        "avg_confidence": None,
        "verification_failures": 0,
        "non_cache_verified": 0,
        "total_cost_usd": None,
        "avg_cost_usd": None,
        "citation_valid_true": 0,
        "citation_valid_nonnull": 0,
        "feedback_up": 0,
        "feedback_down": 0,
    }
    cur = _RoutingCursor(totals=totals)
    result = _run_stats(cur, start=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert result["feedback_up_rate"] is None
    assert result["feedback_down_rate"] is None
    assert result["verification_failure_rate"] is None
    assert result["citation_validity_rate"] is None


# --- graceful degradation: each 035 column absent independently --------------


def test_stats_absent_cost_usd_returns_null_cost_and_omits_no_sql():
    totals = {
        "query_volume": 2,
        "avg_latency_ms": 90.0,
        "p95_latency_ms": 90.0,
        "avg_confidence": 0.9,
        "verification_failures": 0,
        "non_cache_verified": 1,
        "citation_valid_true": 1,
        "citation_valid_nonnull": 1,
        "feedback_up": 0,
        "feedback_down": 0,
    }
    by_model = [{"model_used": "haiku", "model_id": "anthropic/x",
                 "query_volume": 2, "avg_latency_ms": 90.0, "avg_confidence": 0.9}]
    by_day = [{"day": datetime(2026, 1, 1, tzinfo=timezone.utc),
               "query_volume": 2, "avg_latency_ms": 90.0}]
    cur = _RoutingCursor(present_columns=("citation_valid", "model_id"),
                         totals=totals, by_model=by_model, by_day=by_day)
    result = _run_stats(cur, start=datetime(2026, 1, 1, tzinfo=timezone.utc))
    sql = _stats_sql(cur)
    # cost_usd must NOT be referenced anywhere when its column is absent.
    assert "cost_usd" not in sql
    assert result["total_cost_usd"] is None
    assert result["avg_cost_usd"] is None
    assert "avg_cost_usd" not in result["by_model"][0]
    assert "avg_cost_usd" not in result["by_day"][0]
    # Other metrics still computed.
    assert result["citation_validity_rate"] == 1.0
    assert result["by_model"][0]["model_id"] == "anthropic/x"


def test_stats_absent_citation_valid_returns_null_validity():
    totals = {
        "query_volume": 2,
        "avg_latency_ms": 90.0,
        "p95_latency_ms": 90.0,
        "avg_confidence": 0.9,
        "verification_failures": 0,
        "non_cache_verified": 1,
        "total_cost_usd": 0.04,
        "avg_cost_usd": 0.02,
        "feedback_up": 0,
        "feedback_down": 0,
    }
    cur = _RoutingCursor(present_columns=("cost_usd", "model_id"), totals=totals)
    result = _run_stats(cur, start=datetime(2026, 1, 1, tzinfo=timezone.utc))
    sql = _stats_sql(cur)
    assert "citation_valid" not in sql
    assert result["citation_validity_rate"] is None
    # cost still available.
    assert result["total_cost_usd"] == 0.04


def test_stats_absent_model_id_omits_from_by_model():
    totals = {
        "query_volume": 1,
        "avg_latency_ms": 90.0,
        "p95_latency_ms": 90.0,
        "avg_confidence": 0.9,
        "verification_failures": 0,
        "non_cache_verified": 1,
        "total_cost_usd": 0.02,
        "avg_cost_usd": 0.02,
        "citation_valid_true": 1,
        "citation_valid_nonnull": 1,
        "feedback_up": 0,
        "feedback_down": 0,
    }
    by_model = [{"model_used": "haiku", "query_volume": 1,
                 "avg_latency_ms": 90.0, "avg_confidence": 0.9, "avg_cost_usd": 0.02}]
    cur = _RoutingCursor(present_columns=("cost_usd", "citation_valid"),
                         totals=totals, by_model=by_model)
    result = _run_stats(cur, start=datetime(2026, 1, 1, tzinfo=timezone.utc))
    sql = _stats_sql(cur)
    # model_id column must not be selected/grouped when absent.
    assert "model_id" not in sql
    assert "GROUP BY model_used, model_id" not in sql
    assert "model_id" not in result["by_model"][0]
    assert result["by_model"][0]["model_used"] == "haiku"


def test_stats_all_035_columns_absent_nulls_all_optional_metrics():
    totals = {
        "query_volume": 1,
        "avg_latency_ms": 90.0,
        "p95_latency_ms": 90.0,
        "avg_confidence": 0.9,
        "verification_failures": 0,
        "non_cache_verified": 1,
        "feedback_up": 0,
        "feedback_down": 0,
    }
    by_model = [{"model_used": "haiku", "query_volume": 1,
                 "avg_latency_ms": 90.0, "avg_confidence": 0.9}]
    cur = _RoutingCursor(present_columns=(), totals=totals, by_model=by_model)
    result = _run_stats(cur, start=datetime(2026, 1, 1, tzinfo=timezone.utc))
    sql = _stats_sql(cur)
    assert "cost_usd" not in sql
    assert "citation_valid" not in sql
    assert "model_id" not in sql
    assert result["total_cost_usd"] is None
    assert result["avg_cost_usd"] is None
    assert result["citation_validity_rate"] is None
    assert "model_id" not in result["by_model"][0]
    assert "avg_cost_usd" not in result["by_model"][0]
