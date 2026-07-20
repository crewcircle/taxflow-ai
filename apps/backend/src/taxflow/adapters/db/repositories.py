"""Concrete psycopg2 repositories implementing
:class:`taxflow.ports.relational.RelationalDataPort` (Task B4).

All relational data access lives here. This replaces the dual Supabase-PostgREST
(``sb.table(...)``/``sb.rpc(...)``) + scattered raw ``get_pg_conn()`` SQL with a
single set of repository classes behind the ``Repositories`` facade. Every method
uses the shared psycopg2 connection pool (:func:`taxflow.db.get_pg_conn`):

  - Reads use a ``RealDictCursor`` and return plain dicts/lists shaped exactly
    like the rows routers consumed before.
  - Writes commit explicitly (``conn.commit()``) and use ``INSERT ... RETURNING``
    where the caller needs the new row.
  - **Every client-scoped query carries an explicit ``WHERE client_id = %s``**
    ported verbatim from the old ``.eq("client_id", ...)`` filters. RLS
    (008_rls.sql) keys on ``auth.role() = 'service_role'`` and provides no
    per-client isolation, so scoping must live in the query.

The connect/cursor/execute/fetch/commit/close boilerplate is centralised in the
``_fetchone/_fetchall/_fetchval/_fetchcol/_execute`` module helpers so each repo
method is just its SQL + params — the security-relevant scoping predicates stay
fully visible in the SQL string. Loop/multi-statement methods that need a single
transaction (``insert_unseen``, ``upsert_chunks``, ``reset_demo_rows``) keep an
explicit ``with get_pg_conn()`` block.

The synchronous psycopg2 work is designed to run under ``asyncio.to_thread`` by
callers that ``await`` (matching ``services/answer_cache.py``); the repository
methods themselves are plain sync functions.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal

import psycopg2.extras

from taxflow.config import settings
from taxflow.db import get_pg_conn

logger = logging.getLogger(__name__)

# The three additive columns migration 035 adds to ``queries``. The admin stats
# aggregate (Task 2b) and the Tier 3 drift job must degrade gracefully when they
# are absent (this branch predates 035), returning null for the dependent
# metrics instead of failing the query.
_OBSERVABILITY_035_COLUMNS = ("cost_usd", "citation_valid", "model_id")


def _dict_cursor(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def _maybe_json(value):
    """Serialise dict/list values to JSON for jsonb columns (citations,
    verification_result). psycopg2 does not adapt raw dict/list to jsonb."""
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return value


# --- shared statement helpers ------------------------------------------------
# Each wraps the borrow-connection/execute/close boilerplate so repo methods are
# just SQL + params. The SQL (including every ``WHERE client_id = %s`` scoping
# predicate) stays in the caller, so client-scoping remains explicit + readable.


def _fetchone(sql: str, params=()) -> dict | None:
    """Run a SELECT and return the first row as a plain dict (or None)."""
    with get_pg_conn() as conn:
        cur = _dict_cursor(conn)
        cur.execute(sql, params)
        row = cur.fetchone()
        cur.close()
        return dict(row) if row else None


def _fetchall(sql: str, params=()) -> list[dict]:
    """Run a SELECT and return all rows as plain dicts."""
    with get_pg_conn() as conn:
        cur = _dict_cursor(conn)
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        return [dict(r) for r in rows]


def _fetchval(sql: str, params=()):
    """Run a SELECT and return the first column of the first row (or None)."""
    with get_pg_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
        cur.close()
        return row[0] if row else None


def _fetchcol(sql: str, params=()) -> list:
    """Run a SELECT and return the first column of every row as a list."""
    with get_pg_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        return [r[0] for r in rows]


def _execute(sql: str, params=(), *, returning: bool = False) -> dict | None:
    """Run a write statement and commit. With ``returning=True`` returns the
    ``RETURNING`` row as a plain dict (or None); otherwise returns None."""
    with get_pg_conn() as conn:
        cur = _dict_cursor(conn) if returning else conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone() if returning else None
        conn.commit()
        cur.close()
        return dict(row) if (returning and row) else None


def _insert_sql(table: str, cols: list[str], *, returning: bool = True) -> str:
    """Build an ``INSERT INTO <table> (...) VALUES (...)`` statement from column
    names, optionally with ``RETURNING *``."""
    placeholders = ", ".join(["%s"] * len(cols))
    col_sql = ", ".join(cols)
    sql = f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders})"
    return sql + " RETURNING *" if returning else sql


def _set_clause(cols: list[str]) -> str:
    return ", ".join(f"{c} = %s" for c in cols)


def _present_035_columns() -> set[str]:
    """Return which of the migration-035 observability columns
    (``cost_usd``/``citation_valid``/``model_id``) currently exist on
    ``queries``.

    Admin stats + the drift job must degrade gracefully when 035 has not landed
    yet (this branch predates it): a single ``information_schema.columns`` lookup
    tells the aggregate which optional fields it can reference so a missing
    column returns ``null`` for its metric instead of raising ``UndefinedColumn``.
    """
    rows = _fetchcol(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'queries' AND column_name = ANY(%s)
        """,
        (list(_OBSERVABILITY_035_COLUMNS),),
    )
    return set(rows)


def _num(value):
    """Coerce a psycopg2 numeric/Decimal aggregate to a float (or None)."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _int(value) -> int:
    return int(value) if value is not None else 0


# --- clients -----------------------------------------------------------------
class ClientsRepo:
    def get_by_email(self, email: str) -> dict | None:
        return _fetchone("SELECT * FROM clients WHERE email = %s", (email,))

    def get_by_id(self, client_id: str) -> dict | None:
        return _fetchone("SELECT * FROM clients WHERE id = %s", (client_id,))

    def create(self, row: dict) -> dict:
        cols = list(row.keys())
        return _execute(
            _insert_sql("clients", cols), [row[c] for c in cols], returning=True
        )

    def update(self, client_id: str, fields: dict) -> dict | None:
        if not fields:
            return self.get_by_id(client_id)
        cols = list(fields.keys())
        return _execute(
            f"UPDATE clients SET {_set_clause(cols)} WHERE id = %s RETURNING *",
            [_maybe_json(fields[c]) for c in cols] + [client_id],
            returning=True,
        )

    def set_subscription_by_stripe_subscription_id(self, subscription_id: str, fields: dict) -> None:
        cols = list(fields.keys())
        _execute(
            f"UPDATE clients SET {_set_clause(cols)} WHERE stripe_subscription_id = %s",
            [fields[c] for c in cols] + [subscription_id],
        )

    def set_subscription_by_customer_id(self, customer_id: str, fields: dict) -> None:
        cols = list(fields.keys())
        _execute(
            f"UPDATE clients SET {_set_clause(cols)} WHERE stripe_customer_id = %s",
            [fields[c] for c in cols] + [customer_id],
        )

    def activate_from_checkout(self, client_id: str, fields: dict) -> None:
        cols = list(fields.keys())
        _execute(
            f"UPDATE clients SET {_set_clause(cols)} WHERE id = %s",
            [fields[c] for c in cols] + [client_id],
        )

    def find_demo_emails(self, persona: str | None = None) -> list[str]:
        if persona:
            return _fetchcol(
                "SELECT email FROM clients WHERE is_demo = true AND business_type = %s",
                (persona,),
            )
        return _fetchcol("SELECT email FROM clients WHERE is_demo = true")

    def email_exists(self, email: str) -> bool:
        return _fetchval("SELECT 1 FROM clients WHERE email = %s", (email,)) is not None

    def get_voice_sample(self, client_id: str) -> str | None:
        return _fetchval("SELECT voice_sample FROM clients WHERE id = %s", (client_id,)) or None


# --- trials ------------------------------------------------------------------
class TrialsRepo:
    def create(self, client_id: str) -> dict:
        return _execute(
            "INSERT INTO trials (client_id) VALUES (%s) RETURNING *",
            (client_id,),
            returning=True,
        )

    def latest_for_client(self, client_id: str) -> dict | None:
        return _fetchone(
            """
            SELECT * FROM trials
            WHERE client_id = %s
            ORDER BY trial_started_at DESC
            LIMIT 1
            """,
            (client_id,),
        )

    def increment_usage(self, client_id: str, metric: str) -> None:
        _execute("SELECT increment_trial_usage(%s, %s)", (client_id, metric))


# --- queries -----------------------------------------------------------------
class QueriesRepo:
    def list_recent(self, client_id: str, limit: int) -> list[dict]:
        return _fetchall(
            """
            SELECT id, question, status, model_used, confidence_score,
                   verification_result, client_ref, context_note, topic_tag,
                   session_id, re_research_status, created_at
            FROM queries
            WHERE client_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (client_id, limit),
        )

    def insert(self, row: dict) -> dict:
        cols = list(row.keys())
        return _execute(
            _insert_sql("queries", cols),
            [_maybe_json(row[c]) for c in cols],
            returning=True,
        )

    def update(self, client_id: str, query_id: str, fields: dict) -> None:
        if not fields:
            return
        assignments = []
        params: list = []
        for c, value in fields.items():
            if c == "completed_at" and value == "now()":
                assignments.append(f"{c} = now()")
            else:
                assignments.append(f"{c} = %s")
                params.append(_maybe_json(value))
        params.extend([query_id, client_id])
        _execute(
            f"UPDATE queries SET {', '.join(assignments)} "
            "WHERE id = %s AND client_id = %s",
            params,
        )

    def get_for_client(self, client_id: str, query_id: str) -> dict | None:
        return _fetchone(
            "SELECT * FROM queries WHERE id = %s AND client_id = %s",
            (query_id, client_id),
        )

    def get_question_citations(self, client_id: str, query_id: str) -> dict | None:
        # Scoped by BOTH id AND client_id: the pre-refactor documents.py read by
        # query_id only; the client predicate is added here to prevent one client
        # from probing/using another client's query.
        return _fetchone(
            "SELECT question, citations FROM queries WHERE id = %s AND client_id = %s",
            (query_id, client_id),
        )

    def list_session_history(self, client_id: str, session_id: str, limit: int) -> list[dict]:
        # Pins BOTH client_id and session_id so session context never bleeds
        # across sessions/engagements or across clients (absorbs the raw SQL that
        # used to live in research._load_session_history). Rows come back
        # newest-first; the caller reverses to oldest-first for conversation order.
        return _fetchall(
            """
            SELECT question, final_answer
            FROM queries
            WHERE client_id = %s AND session_id = %s
              AND status = 'completed' AND final_answer IS NOT NULL
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (client_id, session_id, limit),
        )

    def set_re_research_status(self, client_id: str, query_id: str, status: str) -> None:
        # Scoped by BOTH id AND client_id so the async worker can only touch the
        # requesting client's query.
        _execute(
            "UPDATE queries SET re_research_status = %s "
            "WHERE id = %s AND client_id = %s",
            (status, query_id, client_id),
        )

    def get_answer_for_client(self, client_id: str, query_id: str) -> dict | None:
        # The async re-research worker reloads the original answer to re-run it.
        # Scoped by BOTH id AND client_id so one client's answer can never be
        # re-researched under another client.
        return _fetchone(
            """
            SELECT question, final_answer, citations, session_id, client_ref
            FROM queries
            WHERE id = %s AND client_id = %s
            """,
            (query_id, client_id),
        )

    def stats(self, start, end=None, client_id=None) -> dict:
        """Operational aggregate over ``queries`` for the half-open window
        ``[start, end)`` (Task 2b). ``end=None`` means "up to now" (the admin
        endpoint passes it; the drift job passes explicit current/baseline
        bounds). ``client_id=None`` aggregates across all clients (operator-global).

        Window contract: ``created_at >= start AND (end IS NULL OR created_at <
        end)`` — an explicit half-open range, never ``since``-to-now.

        Cache rows (``model_used = 'cache'``) are kept in ``query_volume`` but
        excluded from cost/latency/quality/validity means via
        ``FILTER (WHERE model_used <> 'cache')``.

        Feedback is one-to-many (``query_feedback`` has no unique constraint on
        ``query_id``), so it is computed in a SEPARATE CTE over the same window
        and cross-joined — never LEFT JOINed into the per-query aggregate, which
        would duplicate query rows and inflate volume/averages/p95/cost.

        Graceful degradation: the three migration-035 columns (``cost_usd``,
        ``citation_valid``, ``model_id``) may be absent on this branch. We detect
        which exist once via ``information_schema`` and omit the missing ones,
        returning ``null`` for their metrics (``total_cost_usd``/``avg_cost_usd``,
        ``citation_validity_rate``) and dropping ``model_id`` from ``by_model``.
        """
        present = _present_035_columns()
        has_cost = "cost_usd" in present
        has_citation = "citation_valid" in present
        has_model_id = "model_id" in present

        params = {"start": start, "end": end, "client_id": client_id}

        # Half-open [start, end) window + optional operator/client scoping. Both
        # the queries CTE and the feedback CTE reference the SAME window.
        window = (
            "created_at >= %(start)s\n"
            "  AND (%(end)s::timestamptz IS NULL OR created_at < %(end)s)\n"
            "  AND (%(client_id)s::uuid IS NULL OR client_id = %(client_id)s)"
        )
        non_cache = "model_used <> 'cache'"

        # --- totals: query metrics in one CTE (NO feedback join), feedback in a
        # separate CTE, combined via CROSS JOIN so feedback rows never multiply
        # query rows. -----------------------------------------------------------
        cost_select = ""
        if has_cost:
            cost_select = (
                f",\n    sum(cost_usd) FILTER (WHERE {non_cache}) AS total_cost_usd"
                f",\n    avg(cost_usd) FILTER (WHERE {non_cache}) AS avg_cost_usd"
            )
        citation_select = ""
        if has_citation:
            citation_select = (
                f",\n    count(*) FILTER (WHERE {non_cache} AND citation_valid IS TRUE)"
                " AS citation_valid_true"
                f",\n    count(*) FILTER (WHERE {non_cache} AND citation_valid IS NOT NULL)"
                " AS citation_valid_nonnull"
            )

        totals_sql = f"""
            WITH q AS (
                SELECT
                    count(*) AS query_volume,
                    avg(wall_time_ms) FILTER (WHERE {non_cache}) AS avg_latency_ms,
                    percentile_cont(0.95) WITHIN GROUP (ORDER BY wall_time_ms)
                        FILTER (WHERE {non_cache}) AS p95_latency_ms,
                    avg(confidence_score) FILTER (WHERE {non_cache}) AS avg_confidence,
                    count(*) FILTER (
                        WHERE {non_cache}
                        AND verification_result->>'overall_status'
                            IN ('needs_correction', 'unreliable', 'parse_error')
                    ) AS verification_failures,
                    count(*) FILTER (
                        WHERE {non_cache} AND verification_result IS NOT NULL
                    ) AS non_cache_verified{cost_select}{citation_select}
                FROM queries
                WHERE {window}
            ),
            feedback AS (
                SELECT
                    count(*) FILTER (WHERE rating = 'up') AS feedback_up,
                    count(*) FILTER (WHERE rating = 'down') AS feedback_down
                FROM query_feedback
                WHERE {window}
            )
            SELECT q.*, feedback.feedback_up, feedback.feedback_down
            FROM q CROSS JOIN feedback
        """
        totals = _fetchone(totals_sql, params) or {}

        # --- verification_breakdown: GROUP BY overall_status -------------------
        breakdown_rows = _fetchall(
            f"""
            SELECT verification_result->>'overall_status' AS overall_status,
                   count(*) AS count
            FROM queries
            WHERE {window} AND {non_cache} AND verification_result IS NOT NULL
            GROUP BY verification_result->>'overall_status'
            """,
            params,
        )
        verification_breakdown = {
            r["overall_status"]: _int(r["count"]) for r in breakdown_rows
        }

        # --- by_model: GROUP BY model_used (+ concrete model_id when present) --
        # Cache rows are kept in the per-model query_volume/count but excluded
        # from the mean metrics via FILTER (WHERE model_used <> 'cache'),
        # consistent with the totals/by_day paths (so the 'cache' group's
        # averages come back NULL rather than leaking into the breakdown).
        model_id_select = "model_id,\n                   " if has_model_id else ""
        model_cost_select = (
            f",\n                   avg(cost_usd) FILTER (WHERE {non_cache}) AS avg_cost_usd"
            if has_cost
            else ""
        )
        model_group = "model_used, model_id" if has_model_id else "model_used"
        by_model_rows = _fetchall(
            f"""
            SELECT {model_id_select}model_used,
                   count(*) AS query_volume,
                   avg(wall_time_ms) FILTER (WHERE {non_cache}) AS avg_latency_ms,
                   avg(confidence_score) FILTER (WHERE {non_cache}) AS avg_confidence{model_cost_select}
            FROM queries
            WHERE {window}
            GROUP BY {model_group}
            ORDER BY count(*) DESC
            """,
            params,
        )
        by_model = []
        for r in by_model_rows:
            row = {
                "model_used": r["model_used"],
                "query_volume": _int(r["query_volume"]),
                "avg_latency_ms": _num(r["avg_latency_ms"]),
                "avg_confidence": _num(r["avg_confidence"]),
            }
            if has_model_id:
                row["model_id"] = r["model_id"]
            if has_cost:
                row["avg_cost_usd"] = _num(r["avg_cost_usd"])
            by_model.append(row)

        # --- by_day: GROUP BY date_trunc('day', created_at) --------------------
        day_cost_select = (
            f",\n                   avg(cost_usd) FILTER (WHERE {non_cache}) AS avg_cost_usd"
            if has_cost
            else ""
        )
        by_day_rows = _fetchall(
            f"""
            SELECT date_trunc('day', created_at) AS day,
                   count(*) AS query_volume,
                   avg(wall_time_ms) FILTER (WHERE {non_cache}) AS avg_latency_ms{day_cost_select}
            FROM queries
            WHERE {window}
            GROUP BY date_trunc('day', created_at)
            ORDER BY day
            """,
            params,
        )
        by_day = []
        for r in by_day_rows:
            row = {
                "day": r["day"].isoformat() if r.get("day") is not None else None,
                "query_volume": _int(r["query_volume"]),
                "avg_latency_ms": _num(r["avg_latency_ms"]),
            }
            if has_cost:
                row["avg_cost_usd"] = _num(r["avg_cost_usd"])
            by_day.append(row)

        # --- rates (pinned denominators) ---------------------------------------
        feedback_up = _int(totals.get("feedback_up"))
        feedback_down = _int(totals.get("feedback_down"))
        feedback_total = feedback_up + feedback_down
        feedback_up_rate = feedback_up / feedback_total if feedback_total else None
        feedback_down_rate = feedback_down / feedback_total if feedback_total else None

        non_cache_verified = _int(totals.get("non_cache_verified"))
        verification_failures = _int(totals.get("verification_failures"))
        verification_failure_rate = (
            verification_failures / non_cache_verified if non_cache_verified else None
        )

        citation_validity_rate = None
        if has_citation:
            valid_nonnull = _int(totals.get("citation_valid_nonnull"))
            valid_true = _int(totals.get("citation_valid_true"))
            citation_validity_rate = valid_true / valid_nonnull if valid_nonnull else None

        return {
            "query_volume": _int(totals.get("query_volume")),
            "avg_latency_ms": _num(totals.get("avg_latency_ms")),
            "p95_latency_ms": _num(totals.get("p95_latency_ms")),
            "total_cost_usd": _num(totals.get("total_cost_usd")) if has_cost else None,
            "avg_cost_usd": _num(totals.get("avg_cost_usd")) if has_cost else None,
            "avg_confidence": _num(totals.get("avg_confidence")),
            "citation_validity_rate": citation_validity_rate,
            "feedback_up": feedback_up,
            "feedback_down": feedback_down,
            "feedback_up_rate": feedback_up_rate,
            "feedback_down_rate": feedback_down_rate,
            "verification_failure_rate": verification_failure_rate,
            "verification_breakdown": verification_breakdown,
            "by_model": by_model,
            "by_day": by_day,
        }


# --- query_feedback ----------------------------------------------------------
class QueryFeedbackRepo:
    def insert(self, row: dict) -> dict:
        cols = list(row.keys())
        return _execute(
            _insert_sql("query_feedback", cols), [row[c] for c in cols], returning=True
        )


# --- annotations -------------------------------------------------------------
class AnnotationsRepo:
    """Polymorphic annotations/comments (migration 038).

    Every statement carries ``WHERE client_id = %s`` — RLS is service-role-only
    and gives no tenant isolation, so this predicate is the only boundary. The
    ``ON DELETE CASCADE`` self-FK on ``parent_id`` means deleting a root comment
    also removes its replies.
    """

    _COLS = (
        "id, client_id, target_type, target_id, target_version, block_index, "
        "start_offset, end_offset, quoted_text, author_kind, author_name, body, "
        "parent_id, resolved_at, created_at"
    )

    def list_for_target(self, client_id: str, target_type: str, target_id: str) -> list[dict]:
        return _fetchall(
            f"""
            SELECT {self._COLS}
            FROM annotations
            WHERE client_id = %s AND target_type = %s AND target_id = %s
            ORDER BY created_at
            """,
            (client_id, target_type, target_id),
        )

    def insert(self, row: dict) -> dict:
        cols = list(row.keys())
        return _execute(
            _insert_sql("annotations", cols), [row[c] for c in cols], returning=True
        )

    def get_for_client(self, client_id: str, annotation_id: str) -> dict | None:
        return _fetchone(
            f"SELECT {self._COLS} FROM annotations WHERE id = %s AND client_id = %s",
            (annotation_id, client_id),
        )

    def update(self, client_id: str, annotation_id: str, fields: dict) -> dict | None:
        assignments: list[str] = []
        params: list = []
        for c, value in fields.items():
            if value == "now()":
                assignments.append(f"{c} = now()")
            else:
                assignments.append(f"{c} = %s")
                params.append(value)
        if not assignments:
            return self.get_for_client(client_id, annotation_id)
        params.extend([annotation_id, client_id])
        return _execute(
            f"UPDATE annotations SET {', '.join(assignments)} "
            "WHERE id = %s AND client_id = %s RETURNING *",
            params,
            returning=True,
        )

    def delete(self, client_id: str, annotation_id: str) -> None:
        _execute(
            "DELETE FROM annotations WHERE id = %s AND client_id = %s",
            (annotation_id, client_id),
        )


# --- documents ---------------------------------------------------------------
class DocumentsRepo:
    def list_for_client(self, client_id: str, kind_filter: str | None = None) -> list[dict]:
        if kind_filter:
            return _fetchall(
                """
                SELECT id, title, status, context_note, created_at,
                       approved_by, approved_at
                FROM documents
                WHERE client_id = %s AND document_type = %s
                ORDER BY created_at DESC
                """,
                (client_id, kind_filter),
            )
        return _fetchall(
            """
            SELECT id, document_type, title, status, client_ref,
                   context_note, created_at, approved_by, approved_at
            FROM documents
            WHERE client_id = %s
            ORDER BY created_at DESC
            """,
            (client_id,),
        )

    def insert(self, row: dict) -> dict:
        cols = list(row.keys())
        return _execute(
            _insert_sql("documents", cols), [row[c] for c in cols], returning=True
        )

    def get_for_client(self, client_id: str, document_id: str) -> dict | None:
        return _fetchone(
            "SELECT * FROM documents WHERE id = %s AND client_id = %s",
            (document_id, client_id),
        )

    def update_status(
        self, client_id: str, document_id: str, status: str, fields: dict | None = None
    ) -> None:
        assignments = ["status = %s"]
        params: list = [status]
        for c, value in (fields or {}).items():
            if value == "now()":
                assignments.append(f"{c} = now()")
            else:
                assignments.append(f"{c} = %s")
                params.append(value)
        params.extend([document_id, client_id])
        _execute(
            f"UPDATE documents SET {', '.join(assignments)} "
            "WHERE id = %s AND client_id = %s",
            params,
        )


# --- firm_clients (a firm's own client register, built organically) ---------
class FirmClientsRepo:
    def upsert(self, client_id: str, name: str) -> None:
        name = name.strip()
        if not name:
            return
        _execute(
            """
            INSERT INTO firm_clients (client_id, name)
            VALUES (%s, %s)
            ON CONFLICT (client_id, lower(name)) DO NOTHING
            """,
            (client_id, name),
        )

    def create(self, client_id: str, name: str) -> dict:
        """Get-or-create returning the row id (Phase 2 engagement picker).

        Unlike ``upsert`` (no-op, returns nothing) this always returns a real
        ``firm_clients.id`` whether the name is brand-new or already exists:
        ``ON CONFLICT ... DO UPDATE SET name = EXCLUDED.name`` forces the
        conflicting row to be returned. Scoped to the tenant via the
        ``(client_id, lower(name))`` unique index — a name only ever resolves
        within the caller's own client register.
        """
        return _execute(
            """
            INSERT INTO firm_clients (client_id, name)
            VALUES (%s, %s)
            ON CONFLICT (client_id, lower(name))
                DO UPDATE SET name = EXCLUDED.name
            RETURNING id, name
            """,
            (client_id, name.strip()),
            returning=True,
        )

    def list_for_client(self, client_id: str, search: str | None = None) -> list[dict]:
        if search:
            return _fetchall(
                """
                SELECT id, name FROM firm_clients
                WHERE client_id = %s AND name ILIKE %s
                ORDER BY name
                LIMIT 20
                """,
                (client_id, f"%{search}%"),
            )
        return _fetchall(
            "SELECT id, name FROM firm_clients WHERE client_id = %s ORDER BY name LIMIT 200",
            (client_id,),
        )


# --- engagements (first-class engagement entity, migration 039) --------------
class EngagementsRepo:
    """First-class engagements (migration 039).

    Every statement carries ``WHERE client_id = %s`` — RLS is service-role-only
    and gives no tenant isolation, so this predicate is the only boundary. An
    engagement is always attributed to a real ``firm_clients`` row
    (``firm_client_id``) belonging to the same tenant.

    ``create`` allocates the per-firm-client sequential ``engagement_number`` and
    inserts the engagement in a SINGLE transaction: the counter
    ``UPDATE firm_clients ... RETURNING next_engagement_seq`` takes one row lock
    on exactly the target firm-client row (tenant-scoped by
    ``id = %s AND client_id = %s``), so concurrent creates for the same client
    serialise cleanly while different clients never block each other, and the
    first insert can never phantom. If the counter UPDATE returns 0 rows the
    firm-client is unknown or belongs to another tenant — raise, insert nothing.
    """

    _COLS = (
        "id, client_id, firm_client_id, engagement_number, description, "
        "status, created_by, created_at"
    )

    def create(
        self,
        client_id: str,
        firm_client_id: str,
        description: str,
        created_by: str | None = None,
    ) -> dict:
        # Single transaction: increment the per-firm-client counter (row lock),
        # read the new value, then insert the engagement carrying it as
        # engagement_number. One conn.commit() — NOT two _execute calls, which
        # would commit separately and lose atomicity of the number allocation.
        with get_pg_conn() as conn:
            cur = _dict_cursor(conn)
            cur.execute(
                """
                UPDATE firm_clients
                   SET next_engagement_seq = next_engagement_seq + 1
                 WHERE id = %s AND client_id = %s
                RETURNING next_engagement_seq
                """,
                (firm_client_id, client_id),
            )
            seq_row = cur.fetchone()
            if seq_row is None:
                # Unknown firm-client OR one owned by another tenant — never
                # allocate a number or insert an engagement for it.
                cur.close()
                raise ValueError(
                    "firm_client not found for this client (unknown or wrong tenant)"
                )
            engagement_number = seq_row["next_engagement_seq"]
            cur.execute(
                """
                INSERT INTO engagements
                    (client_id, firm_client_id, engagement_number, description, created_by)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
                """,
                (client_id, firm_client_id, engagement_number, description, created_by),
            )
            row = cur.fetchone()
            conn.commit()
            cur.close()
            return dict(row)

    def list_for_client(
        self,
        client_id: str,
        firm_client_id: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        sql = f"SELECT {self._COLS} FROM engagements WHERE client_id = %s"
        params: list = [client_id]
        if firm_client_id:
            sql += " AND firm_client_id = %s"
            params.append(firm_client_id)
        if status:
            sql += " AND status = %s"
            params.append(status)
        sql += " ORDER BY created_at DESC"
        return _fetchall(sql, params)

    def get_for_client(self, client_id: str, engagement_id: str) -> dict | None:
        return _fetchone(
            f"SELECT {self._COLS} FROM engagements WHERE id = %s AND client_id = %s",
            (engagement_id, client_id),
        )


# --- engagement backfill (Phase 2, one-time guarded data step) ---------------
class EngagementBackfillRepo:
    """Read/link helpers for the one-time legacy backfill (scripts/backfill_
    engagements.py). All SQL lives here (architecture gate); the script only
    orchestrates. Every statement is client-scoped.

    ``client_ref`` is normalised with ``NULLIF(TRIM(client_ref), '')`` so blank
    and whitespace-only refs collapse to a single NULL "unattributed" bucket per
    tenant (all legacy ATO uploads land here — they persist no client_ref). The
    backfill only ever touches rows with ``engagement_id IS NULL``, so a second
    run finds no buckets and links nothing — idempotent by construction.
    """

    def distinct_unlinked_buckets(self, client_id: str | None = None) -> list[dict]:
        """Distinct ``(client_id, normalised client_ref)`` across ``queries`` +
        ``documents`` with ``engagement_id IS NULL``. Each returned bucket is
        guaranteed to have at least one unlinked row."""
        client_pred = " AND client_id = %s" if client_id else ""
        sql = f"""
            SELECT DISTINCT client_id, NULLIF(TRIM(client_ref), '') AS client_ref
            FROM (
                SELECT client_id, client_ref FROM queries
                 WHERE engagement_id IS NULL{client_pred}
                UNION
                SELECT client_id, client_ref FROM documents
                 WHERE engagement_id IS NULL{client_pred}
            ) t
            ORDER BY client_id, client_ref NULLS FIRST
        """
        params: list = [client_id, client_id] if client_id else []
        return _fetchall(sql, params)

    def link_bucket(self, client_id: str, client_ref: str | None, engagement_id: str) -> int:
        """Link every unlinked ``queries``/``documents`` row in a bucket to
        ``engagement_id``. Returns the total number of rows linked. Scoped to the
        tenant AND the normalised client_ref (NULL for the unattributed bucket);
        only rows still ``engagement_id IS NULL`` are touched (idempotent)."""
        # Build the client_ref predicate + params once: NULL uses IS NULL (no
        # bound value), a real ref matches the normalised value. Both keep the
        # tenant scope and the engagement_id IS NULL idempotent guard.
        if client_ref is None:
            ref_pred = "NULLIF(TRIM(client_ref), '') IS NULL"
            ref_params: tuple = ()
        else:
            ref_pred = "NULLIF(TRIM(client_ref), '') = %s"
            ref_params = (client_ref,)

        total = 0
        with get_pg_conn() as conn:
            cur = conn.cursor()
            for table in ("queries", "documents"):
                cur.execute(
                    f"""
                    UPDATE {table} SET engagement_id = %s
                     WHERE client_id = %s
                       AND {ref_pred}
                       AND engagement_id IS NULL
                    """,
                    (engagement_id, client_id, *ref_params),
                )
                total += cur.rowcount
            conn.commit()
            cur.close()
        return total


# --- query_sessions ------------------------------------------------------------
class QuerySessionsRepo:
    def list_for_client(self, client_id: str) -> list[dict]:
        return _fetchall(
            "SELECT session_id, label FROM query_sessions WHERE client_id = %s",
            (client_id,),
        )

    def upsert_label(self, client_id: str, session_id: str, label: str) -> dict:
        return _execute(
            """
            INSERT INTO query_sessions (session_id, client_id, label)
            VALUES (%s, %s, %s)
            ON CONFLICT (session_id) DO UPDATE
                SET label = EXCLUDED.label, updated_at = now()
            RETURNING session_id, label
            """,
            (session_id, client_id, label),
            returning=True,
        )


# --- firm_knowledge ----------------------------------------------------------
class FirmKnowledgeRepo:
    def list_for_client(self, client_id: str) -> list[dict]:
        return _fetchall(
            """
            SELECT id, file_name, file_type, usage_count, created_at
            FROM firm_knowledge
            WHERE client_id = %s
            ORDER BY created_at DESC
            """,
            (client_id,),
        )

    def insert(self, row: dict) -> dict:
        cols = list(row.keys())
        return _execute(
            _insert_sql("firm_knowledge", cols), [row[c] for c in cols], returning=True
        )

    def get_for_client(self, client_id: str, item_id: str) -> dict | None:
        return _fetchone(
            """
            SELECT id, file_name, file_type, content, usage_count, created_at
            FROM firm_knowledge
            WHERE id = %s AND client_id = %s
            """,
            (item_id, client_id),
        )

    def delete(self, client_id: str, item_id: str) -> None:
        _execute(
            "DELETE FROM firm_knowledge WHERE id = %s AND client_id = %s",
            (item_id, client_id),
        )

    def increment_usage(self, client_id: str, item_ids: list[str]) -> None:
        # Task C5: bump usage_count for the firm-knowledge items actually CITED
        # in an answer (best-effort — the answer flow swallows failures). Scoped
        # by client_id so one client's usage can never inflate another's, and
        # short-circuits on an empty id list to avoid a pointless DB round-trip.
        if not item_ids:
            return
        _execute(
            "UPDATE firm_knowledge SET usage_count = usage_count + 1 "
            "WHERE client_id = %s AND id = ANY(%s)",
            (client_id, list(item_ids)),
        )

    def usage_trend(self, client_id: str) -> dict:
        """Firm-knowledge usage trend (Task C6) for ``trace.firm.usage_trend``:
        ``{quarter_count, prior_count}`` — the number of firm_knowledge items
        added this calendar quarter vs the immediately prior quarter, scoped by
        ``client_id``. A single grouped query keys off ``created_at`` relative to
        ``date_trunc('quarter', now())`` so the "why this answer?" UI can show
        whether the firm's knowledge base is growing. Best-effort — the caller
        (research agent) swallows failures and renders no trend.
        """
        row = _fetchone(
            """
            SELECT
              count(*) FILTER (
                WHERE created_at >= date_trunc('quarter', now())
              ) AS quarter_count,
              count(*) FILTER (
                WHERE created_at >= date_trunc('quarter', now()) - interval '3 months'
                  AND created_at < date_trunc('quarter', now())
              ) AS prior_count
            FROM firm_knowledge
            WHERE client_id = %s
            """,
            (client_id,),
        )
        return {
            "quarter_count": int(row["quarter_count"]) if row else 0,
            "prior_count": int(row["prior_count"]) if row else 0,
        }


# --- knowledge_suggestions (Task C5) -----------------------------------------
class KnowledgeSuggestionsRepo:
    """Approval-gated learning-loop suggestions (032_knowledge_suggestions).

    A thumbs-up or a saved advice_memo creates a PENDING suggestion here rather
    than writing straight into the authoritative firm_knowledge store. A partner
    then approves (embeds into firm_knowledge, records firm_knowledge_id) or
    rejects it. Every method is scoped by an explicit ``client_id`` predicate.
    """

    _SELECT_COLS = (
        "id, source_query_id, source_document_id, title, content, "
        "reason, status, decided_by, decided_at, firm_knowledge_id, created_at"
    )

    def insert(self, row: dict) -> dict:
        cols = list(row.keys())
        return _execute(
            _insert_sql("knowledge_suggestions", cols),
            [row[c] for c in cols],
            returning=True,
        )

    def list_for_client(self, client_id: str, status: str | None = None) -> list[dict]:
        if status:
            return _fetchall(
                f"SELECT {self._SELECT_COLS} FROM knowledge_suggestions "
                "WHERE client_id = %s AND status = %s ORDER BY created_at DESC",
                (client_id, status),
            )
        return _fetchall(
            f"SELECT {self._SELECT_COLS} FROM knowledge_suggestions "
            "WHERE client_id = %s ORDER BY created_at DESC",
            (client_id,),
        )

    def get_for_client(self, client_id: str, suggestion_id: str) -> dict | None:
        return _fetchone(
            f"SELECT {self._SELECT_COLS} FROM knowledge_suggestions "
            "WHERE id = %s AND client_id = %s",
            (suggestion_id, client_id),
        )

    def set_decision(self, client_id: str, suggestion_id: str, status: str, fields: dict | None = None) -> dict | None:
        # Record an approve/reject decision. Scoped by id AND client_id so a
        # client can only decide on its own suggestions, and guarded by
        # ``status = 'pending'`` so the decision is a check-and-CLAIM: a
        # concurrent double-approve/reject (or a retry of an already-decided
        # suggestion) matches 0 rows and returns None, so the caller does NOT
        # write a second firm_knowledge row. Extra columns (e.g.
        # firm_knowledge_id/decided_by/decided_at) come through ``fields``.
        assignments = ["status = %s"]
        params: list = [status]
        for c, value in (fields or {}).items():
            if c == "decided_at" and value == "now()":
                assignments.append(f"{c} = now()")
            else:
                assignments.append(f"{c} = %s")
                params.append(value)
        params.extend([suggestion_id, client_id])
        return _execute(
            f"UPDATE knowledge_suggestions SET {', '.join(assignments)} "
            "WHERE id = %s AND client_id = %s AND status = 'pending' RETURNING *",
            params,
            returning=True,
        )

    def approve(self, client_id: str, suggestion_id: str, firm_knowledge_row: dict, decided_by: str | None) -> dict | None:
        """Atomically approve a PENDING suggestion (Task C5, idempotent).

        In ONE transaction: (1) claim the suggestion by flipping status
        pending→approved ``WHERE ... AND status = 'pending'`` — the guard makes
        this a check-and-claim, so a concurrent double-approve (or a retry of an
        already-decided suggestion) matches 0 rows; (2) only if the claim
        succeeded, INSERT the authoritative ``firm_knowledge`` row; (3) stamp the
        resulting ``firm_knowledge_id``/``decided_by``/``decided_at`` back onto
        the suggestion. If the claim matches 0 rows we insert NOTHING and return
        None, so exactly one concurrent approver can ever write firm_knowledge and
        an insert-without-decision can't happen (both live in the same txn).
        """
        with get_pg_conn() as conn:
            cur = _dict_cursor(conn)
            # (1) check-and-claim: only a still-pending row is claimed.
            cur.execute(
                "UPDATE knowledge_suggestions SET status = 'approved' "
                "WHERE id = %s AND client_id = %s AND status = 'pending' "
                "RETURNING id",
                (suggestion_id, client_id),
            )
            claimed = cur.fetchone()
            if not claimed:
                # Already decided / claimed by a concurrent request → no insert.
                conn.rollback()
                cur.close()
                return None
            # (2) insert the authoritative firm_knowledge row.
            fk_cols = list(firm_knowledge_row.keys())
            fk_placeholders = ", ".join(["%s"] * len(fk_cols))
            cur.execute(
                f"INSERT INTO firm_knowledge ({', '.join(fk_cols)}) "
                f"VALUES ({fk_placeholders}) RETURNING id",
                [firm_knowledge_row[c] for c in fk_cols],
            )
            fk_id = cur.fetchone()["id"]
            # (3) stamp the decision metadata onto the claimed suggestion.
            cur.execute(
                "UPDATE knowledge_suggestions "
                "SET firm_knowledge_id = %s, decided_by = %s, decided_at = now() "
                "WHERE id = %s AND client_id = %s "
                f"RETURNING {self._SELECT_COLS}",
                (fk_id, decided_by, suggestion_id, client_id),
            )
            row = cur.fetchone()
            conn.commit()
            cur.close()
            return dict(row) if row else None

    def exists_for_query(self, client_id: str, query_id: str) -> bool:
        # De-dup guard: a second thumbs-up on the SAME query must not create a
        # second pending suggestion. Only pending suggestions block a re-create
        # (an approved/rejected one has already been acted on).
        return _fetchval(
            """
            SELECT 1 FROM knowledge_suggestions
            WHERE client_id = %s AND source_query_id = %s AND status = 'pending'
            LIMIT 1
            """,
            (client_id, query_id),
        ) is not None


# --- engagement_context (Task C4) --------------------------------------------
class EngagementContextRepo:
    _SELECT_COLS = (
        "id, client_ref, document_id, document_type, title, content, created_at"
    )

    def insert(self, row: dict) -> dict:
        cols = list(row.keys())
        return _execute(
            _insert_sql("engagement_context", cols),
            [row[c] for c in cols],
            returning=True,
        )

    def list_for_client(self, client_id: str, client_ref: str | None = None) -> list[dict]:
        if client_ref:
            return _fetchall(
                f"SELECT {self._SELECT_COLS} FROM engagement_context "
                "WHERE client_id = %s AND client_ref = %s ORDER BY created_at DESC",
                (client_id, client_ref),
            )
        return _fetchall(
            f"SELECT {self._SELECT_COLS} FROM engagement_context "
            "WHERE client_id = %s ORDER BY created_at DESC",
            (client_id,),
        )


# --- regulatory_alerts -------------------------------------------------------
class RegulatoryAlertsRepo:
    def list_recent(self, limit: int) -> list[dict]:
        # Global feed - not scoped to a client (see routers/regulatory_alerts.py).
        return _fetchall(
            """
            SELECT id, source, alert_type, title, summary, url, detected_at
            FROM regulatory_alerts
            ORDER BY detected_at DESC
            LIMIT %s
            """,
            (limit,),
        )

    def insert_unseen(self, rows: list[dict]) -> int:
        # Absorbs regulatory_monitor's per-item "seen?" SELECT + INSERT: skip any
        # item whose url already exists, insert the rest. Returns inserted count.
        # One transaction for the whole batch, so keep an explicit connection.
        if not rows:
            return 0
        with get_pg_conn() as conn:
            cur = conn.cursor()
            inserted = 0
            for item in rows:
                cur.execute("SELECT 1 FROM regulatory_alerts WHERE url = %s", (item["url"],))
                if cur.fetchone():
                    continue
                cur.execute(
                    "INSERT INTO regulatory_alerts (source, alert_type, title, url) "
                    "VALUES (%s, %s, %s, %s)",
                    (item["source"], item["alert_type"], item["title"], item["url"]),
                )
                inserted += 1
            conn.commit()
            cur.close()
            return inserted


# --- contact -----------------------------------------------------------------
class ContactRepo:
    def insert(self, row: dict) -> dict:
        cols = list(row.keys())
        return _execute(
            _insert_sql("contact_messages", cols), [row[c] for c in cols], returning=True
        )


# --- rate_limit --------------------------------------------------------------
class RateLimitRepo:
    def purge_older_than(self, seconds: int) -> None:
        _execute(
            "DELETE FROM rate_limit_hits WHERE ts < now() - (%s || ' seconds')::interval",
            (seconds,),
        )

    def count_hits(self, key: str, window_seconds: int) -> int:
        count = _fetchval(
            """
            SELECT count(*) FROM rate_limit_hits
            WHERE client_id = %s
              AND ts > now() - (%s || ' seconds')::interval
            """,
            (key, window_seconds),
        )
        return int(count or 0)

    def record_hit(self, key: str) -> None:
        _execute(
            "INSERT INTO rate_limit_hits (client_id, ts) VALUES (%s, now())",
            (key,),
        )


# --- query_cache -------------------------------------------------------------
class QueryCacheRepo:
    def get_cached(self, question_norm: str, client_id: str | None, knowledge_version: int) -> dict | None:
        row = _fetchone(
            """
            SELECT result
            FROM query_cache
            WHERE client_id = %s
              AND question_norm = %s
              AND knowledge_version = %s
              AND created_at > now() - (%s || ' seconds')::interval
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (client_id, question_norm, knowledge_version, settings.ANSWER_CACHE_TTL_SECONDS),
        )
        if not row:
            return None
        result = row["result"]
        return result if isinstance(result, dict) else json.loads(result)

    def put_cached(self, row: dict) -> None:
        _execute(
            """
            INSERT INTO query_cache (client_id, question_norm, knowledge_version, result)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (client_id, question_norm, knowledge_version)
            DO UPDATE SET result = EXCLUDED.result, created_at = now()
            """,
            (
                row["client_id"],
                row["question_norm"],
                row["knowledge_version"],
                json.dumps(row["result"]),
            ),
        )

    def current_knowledge_version(self) -> int:
        version = _fetchval("SELECT version FROM knowledge_version WHERE id = true")
        return int(version) if version is not None else 1

    def bump_knowledge_version(self) -> int:
        row = _execute(
            """
            UPDATE knowledge_version
            SET version = version + 1, updated_at = now()
            WHERE id = true
            RETURNING version
            """,
            returning=True,
        )
        return int(row["version"]) if row else 1

    def count_prior_asks(self, client_id: str, question_norm: str) -> int:
        """Count a client's completed queries whose normalised question text
        matches ``question_norm``. The SQL mirrors ``normalise_question`` in
        answer_cache (lowercase, collapse whitespace, strip surrounding
        punctuation) so a match is a genuine repeat, not a formatting diff.
        """
        count = _fetchval(
            r"""
            SELECT COUNT(*) FROM queries
            WHERE client_id = %s
              AND status = 'completed'
              AND btrim(regexp_replace(lower(btrim(question)), '\s+', ' ', 'g'), E' \t\n?.!') = %s
            """,
            (client_id, question_norm),
        )
        return int(count) if count is not None else 0


# --- knowledge_ingest --------------------------------------------------------
class KnowledgeIngestRepo:
    def upsert_chunks(self, rows: list[dict]) -> int:
        # rows: list of positional tuples matching the INSERT column order (the
        # pipeline builds them). One transaction for the batch. Returns the
        # number of rows upserted.
        if not rows:
            return 0
        with get_pg_conn() as conn:
            cur = conn.cursor()
            for row in rows:
                cur.execute(
                    """
                    INSERT INTO knowledge_chunks
                        (source_type, source_url, source_title, citation, content, embedding,
                         chunk_index, token_count, effective_date, source_object_key, jurisdiction,
                         topic, heading_path, section_ref, chunk_level, parent_key, parent_content,
                         last_scraped_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (source_url, chunk_index) DO UPDATE SET
                        content = EXCLUDED.content,
                        embedding = EXCLUDED.embedding,
                        token_count = EXCLUDED.token_count,
                        source_object_key = EXCLUDED.source_object_key,
                        jurisdiction = EXCLUDED.jurisdiction,
                        topic = EXCLUDED.topic,
                        heading_path = EXCLUDED.heading_path,
                        section_ref = EXCLUDED.section_ref,
                        chunk_level = EXCLUDED.chunk_level,
                        parent_key = EXCLUDED.parent_key,
                        parent_content = EXCLUDED.parent_content,
                        last_scraped_at = now()
                    """,
                    row,
                )
            conn.commit()
            count = len(rows)
            cur.close()
            return count

    def mark_superseded(self, mapping: dict[str, str]) -> int:
        # The B1 fix lands here: mark referenced rulings is_current = false and
        # record which current citation superseded each. ``mapping`` maps a
        # superseded citation -> the superseding (current) citation.
        # Needs cur.rowcount, so keep an explicit connection.
        if not mapping:
            return 0
        old_citations = list(mapping.keys())
        new_citations = [mapping[old] for old in old_citations]
        with get_pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE knowledge_chunks AS kc
                SET is_current = false, superseded_by = m.new_citation
                FROM unnest(%s::text[], %s::text[]) AS m(old_citation, new_citation)
                WHERE kc.citation = m.old_citation
                """,
                (old_citations, new_citations),
            )
            count = cur.rowcount
            conn.commit()
            cur.close()
            return count

    def stale_urls(self, urls: list[str]) -> list[str]:
        # URLs not scraped in the last 24h (or never scraped).
        if not urls:
            return []
        fresh = set(
            _fetchcol(
                """
                SELECT DISTINCT source_url FROM knowledge_chunks
                WHERE source_url = ANY(%s)
                  AND last_scraped_at > now() - interval '24 hours'
                """,
                (urls,),
            )
        )
        return [u for u in urls if u not in fresh]

    def graph_metadata(self) -> list[dict]:
        """One aggregated row per citation for the knowledge-graph/table explorer.

        Metadata-only (never chunk ``content``): enough per citation to browse,
        filter, and audit the knowledge base - including ``cited_count``, real
        usage data (how many times this citation has actually appeared in an
        answer, via ``queries.citations``) rather than leaving "which sources
        were used" for the frontend to guess at. Powers ``GET /knowledge/graph``.
        """
        return _fetchall(
            """
            WITH citation_counts AS (
                SELECT elem ->> 'citation' AS citation, count(*) AS cited_count
                FROM queries, jsonb_array_elements(citations) AS elem
                WHERE citations IS NOT NULL
                GROUP BY elem ->> 'citation'
            )
            SELECT
                kc.citation,
                min(kc.source_title) AS title,
                min(kc.source_type) AS source_type,
                min(kc.jurisdiction) AS jurisdiction,
                min(kc.source_url) AS source_url,
                count(*) AS chunk_count,
                bool_and(kc.is_current) AS is_current,
                max(kc.last_scraped_at) AS last_scraped_at,
                array_agg(DISTINCT kc.topic) FILTER (WHERE kc.topic IS NOT NULL) AS topics,
                coalesce(max(cc.cited_count), 0) AS cited_count
            FROM knowledge_chunks kc
            LEFT JOIN citation_counts cc ON cc.citation = kc.citation
            GROUP BY kc.citation
            ORDER BY kc.citation
            """
        )

    def delete_by_source_url(self, source_url: str) -> int:
        """Delete every chunk row for one ``source_url``. Returns the row count.

        Used by the re-chunk backfill (Task C4): hierarchical chunking produces a
        different chunk count than the flat path, so a plain
        ``ON CONFLICT (source_url, chunk_index)`` re-upsert would leave stale
        high-index flat rows behind. Delete-before-reinsert clears the old rows
        first so only the freshly-produced hierarchical chunks remain.
        """
        with get_pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM knowledge_chunks WHERE source_url = %s",
                (source_url,),
            )
            count = cur.rowcount
            conn.commit()
            cur.close()
            return count

    def list_ingested_sources(self) -> list[dict]:
        """One row per distinct ``source_url`` with the fields ``process_document``
        needs to rebuild ``metadata`` during the Task C4 re-chunk backfill.

        The aggregates pick a single representative value per source_url (all
        chunks of one document share these), matching the keys the pipeline reads
        from ``metadata`` (``url`` maps from ``source_url``).
        """
        return _fetchall(
            """
            SELECT
                source_url,
                min(source_type) AS source_type,
                min(source_title) AS title,
                min(citation) AS citation,
                min(effective_date) AS effective_date,
                min(jurisdiction) AS jurisdiction,
                min(source_object_key) AS source_object_key
            FROM knowledge_chunks
            WHERE source_url IS NOT NULL
            GROUP BY source_url
            ORDER BY source_url
            """
        )


# --- demo_reset --------------------------------------------------------------
class DemoResetRepo:
    def reset_demo_rows(self) -> None:
        # Multi-statement transaction over the demo client ids, so keep an
        # explicit connection.
        with get_pg_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM clients WHERE is_demo = true")
            demo_ids = [r[0] for r in cur.fetchall()]
            if demo_ids:
                # annotations have NO FK to queries/documents (target_id is
                # polymorphic), so nothing cascades — delete them explicitly
                # BEFORE the queries/documents deletes to avoid orphan rows.
                cur.execute("DELETE FROM annotations WHERE client_id = ANY(%s)", (demo_ids,))
                cur.execute("DELETE FROM documents WHERE client_id = ANY(%s)", (demo_ids,))
                # query_feedback FK cascades from queries (migration 020), but
                # delete it explicitly first so the reset also works before that
                # migration is applied and doesn't rely on cascade ordering.
                cur.execute("DELETE FROM query_feedback WHERE client_id = ANY(%s)", (demo_ids,))
                cur.execute("DELETE FROM queries WHERE client_id = ANY(%s)", (demo_ids,))
                conn.commit()
                logger.info("demo reset: cleared queries/documents for %d demo client(s)", len(demo_ids))
            cur.close()


# --- health ------------------------------------------------------------------
class HealthRepo:
    def ping(self) -> bool:
        _fetchval("SELECT 1")
        return True


# --- re_research_jobs --------------------------------------------------------
class ReResearchJobsRepo:
    """Async feedback re-research job queue (030_re_research_jobs_notifications).

    Idempotency/at-most-once contract:
      - ``enqueue`` uses ``ON CONFLICT (feedback_id) DO NOTHING RETURNING *`` so a
        duplicate feedback never produces a second job (returns None on dup).
      - ``claim_next`` sets ``status='running'`` inside the SAME statement that
        selects the row (``FOR UPDATE SKIP LOCKED``), so once claimed the row is
        no longer ``queued`` and no other worker re-claims it.
    """

    def enqueue(self, row: dict) -> dict | None:
        cols = list(row.keys())
        return _execute(
            _insert_sql("re_research_jobs", cols, returning=False)
            + " ON CONFLICT (feedback_id) DO NOTHING RETURNING *",
            [_maybe_json(row[c]) for c in cols],
            returning=True,
        )

    def claim_next(self) -> dict | None:
        # Atomic claim: the UPDATE sets status='running' + increments attempts on
        # exactly one queued, due row selected FOR UPDATE SKIP LOCKED so
        # concurrent workers never grab the same job.
        return _execute(
            """
            UPDATE re_research_jobs
            SET status = 'running', attempts = attempts + 1, updated_at = now()
            WHERE id = (
                SELECT id FROM re_research_jobs
                WHERE status = 'queued' AND next_attempt_at <= now()
                ORDER BY next_attempt_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING *
            """,
            (),
            returning=True,
        )

    def requeue(self, job_id: str, error: str, backoff_seconds: int) -> None:
        # Transient failure with attempts left: back to 'queued' with a future
        # next_attempt_at so claim_next picks it up again after the backoff.
        _execute(
            "UPDATE re_research_jobs "
            "SET status = 'queued', error_message = %s, "
            "next_attempt_at = now() + make_interval(secs => %s), updated_at = now() "
            "WHERE id = %s",
            (error, backoff_seconds, job_id),
        )

    def mark(self, job_id: str, status: str, fields: dict | None = None) -> None:
        # Terminal done/failed (plus any extra columns, e.g. error_message).
        assignments = ["status = %s"]
        params: list = [status]
        for c, value in (fields or {}).items():
            assignments.append(f"{c} = %s")
            params.append(_maybe_json(value))
        assignments.append("updated_at = now()")
        params.append(job_id)
        _execute(
            f"UPDATE re_research_jobs SET {', '.join(assignments)} WHERE id = %s",
            params,
        )


# --- notifications -----------------------------------------------------------
class NotificationsRepo:
    def insert(self, row: dict) -> dict:
        cols = list(row.keys())
        return _execute(
            _insert_sql("notifications", cols),
            [_maybe_json(row[c]) for c in cols],
            returning=True,
        )

    def list_for_client(self, client_id: str, limit: int = 50) -> list[dict]:
        return _fetchall(
            """
            SELECT id, kind, query_id, title, body, read_at, created_at
            FROM notifications
            WHERE client_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (client_id, limit),
        )

    def mark_read(self, client_id: str, notification_id: str) -> None:
        # Scoped by BOTH id AND client_id so a client can only mark its own
        # notifications read.
        _execute(
            "UPDATE notifications SET read_at = now() "
            "WHERE id = %s AND client_id = %s",
            (notification_id, client_id),
        )


# --- ops notifications -------------------------------------------------------
class OpsNotificationsRepo:
    """Operator-scoped notifications (037_ops_notifications).

    Unlike the per-client ``NotificationsRepo`` above, these rows have NO
    ``client_id`` — they are operator-global (e.g. drift alerts) and read behind
    the admin token, so there is no per-client scoping predicate here.
    """

    def insert(self, row: dict) -> dict:
        cols = list(row.keys())
        return _execute(
            _insert_sql("ops_notifications", cols),
            [_maybe_json(row[c]) for c in cols],
            returning=True,
        )

    def latest(self, limit: int = 50) -> list[dict]:
        return _fetchall(
            """
            SELECT id, kind, title, body, metadata, severity, read_at, created_at
            FROM ops_notifications
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        )

    def mark_read(self, notification_id: str) -> None:
        _execute(
            "UPDATE ops_notifications SET read_at = now() WHERE id = %s",
            (notification_id,),
        )


# --- production quality snapshots --------------------------------------------
class ProductionSnapshotsRepo:
    """Production-drift snapshots (036_production_quality_snapshots).

    Operator-scoped (no client_id): one row per drift-monitor run, holding the
    rolled-up ``metrics`` + ``diff`` jsonb blobs and the denormalised
    ``has_regressions`` flag the admin dashboard / ops alert read directly.
    """

    def insert(self, row: dict) -> dict:
        cols = list(row.keys())
        return _execute(
            _insert_sql("production_quality_snapshots", cols),
            [_maybe_json(row[c]) for c in cols],
            returning=True,
        )

    def latest(self, limit: int = 30) -> list[dict]:
        return _fetchall(
            """
            SELECT id, window_start, window_end, baseline_start, baseline_end,
                   metrics, diff, has_regressions, created_at
            FROM production_quality_snapshots
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        )

    def baseline_window(self, start, end) -> list[dict]:
        # Snapshots whose run landed in an explicit [start, end) window — used to
        # look back over a trailing baseline period. Mirrors the [start, end)
        # windowed contract QueriesRepo.stats uses.
        return _fetchall(
            """
            SELECT id, window_start, window_end, baseline_start, baseline_end,
                   metrics, diff, has_regressions, created_at
            FROM production_quality_snapshots
            WHERE created_at >= %s AND created_at < %s
            ORDER BY created_at DESC
            """,
            (start, end),
        )


class Repositories:
    """Concrete ``RelationalDataPort`` facade wiring one repo per aggregate."""
    def __init__(self) -> None:
        self.clients = ClientsRepo()
        self.trials = TrialsRepo()
        self.queries = QueriesRepo()
        self.query_feedback = QueryFeedbackRepo()
        self.annotations = AnnotationsRepo()
        self.documents = DocumentsRepo()
        self.firm_clients = FirmClientsRepo()
        self.engagements = EngagementsRepo()
        self.engagement_backfill = EngagementBackfillRepo()
        self.query_sessions = QuerySessionsRepo()
        self.firm_knowledge = FirmKnowledgeRepo()
        self.knowledge_suggestions = KnowledgeSuggestionsRepo()
        self.engagement_context = EngagementContextRepo()
        self.regulatory_alerts = RegulatoryAlertsRepo()
        self.contact = ContactRepo()
        self.rate_limit = RateLimitRepo()
        self.query_cache = QueryCacheRepo()
        self.knowledge_ingest = KnowledgeIngestRepo()
        self.demo_reset = DemoResetRepo()
        self.health = HealthRepo()
        self.re_research_jobs = ReResearchJobsRepo()
        self.notifications = NotificationsRepo()
        self.ops_notifications = OpsNotificationsRepo()
        self.production_snapshots = ProductionSnapshotsRepo()
