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

import psycopg2.extras

from taxflow.config import settings
from taxflow.db import get_pg_conn


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
            [fields[c] for c in cols] + [client_id],
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
                   created_at
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


# --- query_feedback ----------------------------------------------------------
class QueryFeedbackRepo:
    def insert(self, row: dict) -> dict:
        cols = list(row.keys())
        return _execute(
            _insert_sql("query_feedback", cols), [row[c] for c in cols], returning=True
        )


# --- documents ---------------------------------------------------------------
class DocumentsRepo:
    def list_for_client(self, client_id: str, kind_filter: str | None = None) -> list[dict]:
        if kind_filter:
            return _fetchall(
                """
                SELECT id, title, status, context_note, created_at
                FROM documents
                WHERE client_id = %s AND document_type = %s
                ORDER BY created_at DESC
                """,
                (client_id, kind_filter),
            )
        return _fetchall(
            """
            SELECT id, document_type, title, status, client_ref,
                   context_note, created_at
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
                         topic, last_scraped_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (source_url, chunk_index) DO UPDATE SET
                        content = EXCLUDED.content,
                        embedding = EXCLUDED.embedding,
                        token_count = EXCLUDED.token_count,
                        source_object_key = EXCLUDED.source_object_key,
                        jurisdiction = EXCLUDED.jurisdiction,
                        topic = EXCLUDED.topic,
                        last_scraped_at = now()
                    """,
                    row,
                )
            conn.commit()
            count = len(rows)
            cur.close()
            return count

    def mark_superseded(self, citations: set[str]) -> int:
        # The B1 fix lands here: mark referenced rulings is_current = false.
        # Needs cur.rowcount, so keep an explicit connection.
        if not citations:
            return 0
        with get_pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE knowledge_chunks SET is_current = false WHERE citation = ANY(%s)",
                (list(citations),),
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
        """One aggregated row per citation for the knowledge-graph explorer.

        Metadata-only (never chunk ``content``): enough per citation to browse
        and filter the knowledge base and cluster documents by their classified
        topic(s). Powers ``GET /knowledge/graph``.
        """
        return _fetchall(
            """
            SELECT
                citation,
                min(source_title) AS title,
                min(source_type) AS source_type,
                min(jurisdiction) AS jurisdiction,
                min(source_url) AS source_url,
                count(*) AS chunk_count,
                bool_and(is_current) AS is_current,
                max(last_scraped_at) AS last_scraped_at,
                array_agg(DISTINCT topic) FILTER (WHERE topic IS NOT NULL) AS topics
            FROM knowledge_chunks
            GROUP BY citation
            ORDER BY citation
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
                cur.execute("DELETE FROM documents WHERE client_id = ANY(%s)", (demo_ids,))
                # query_feedback FK cascades from queries (migration 020), but
                # delete it explicitly first so the reset also works before that
                # migration is applied and doesn't rely on cascade ordering.
                cur.execute("DELETE FROM query_feedback WHERE client_id = ANY(%s)", (demo_ids,))
                cur.execute("DELETE FROM queries WHERE client_id = ANY(%s)", (demo_ids,))
                conn.commit()
                print(f"demo reset: cleared queries/documents for {len(demo_ids)} demo client(s)")
            cur.close()


# --- health ------------------------------------------------------------------
class HealthRepo:
    def ping(self) -> bool:
        _fetchval("SELECT 1")
        return True


class Repositories:
    """Concrete ``RelationalDataPort`` facade wiring one repo per aggregate."""

    def __init__(self) -> None:
        self.clients = ClientsRepo()
        self.trials = TrialsRepo()
        self.queries = QueriesRepo()
        self.query_feedback = QueryFeedbackRepo()
        self.documents = DocumentsRepo()
        self.firm_knowledge = FirmKnowledgeRepo()
        self.regulatory_alerts = RegulatoryAlertsRepo()
        self.contact = ContactRepo()
        self.rate_limit = RateLimitRepo()
        self.query_cache = QueryCacheRepo()
        self.knowledge_ingest = KnowledgeIngestRepo()
        self.demo_reset = DemoResetRepo()
        self.health = HealthRepo()
