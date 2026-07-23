"""E2E deploy gate — the test that would have caught the prod outage.

Applies all 41 migrations to a real Postgres (via the ``_migrated_db`` /
``authed_client`` fixtures) and exercises the shipped read + CRUD query shapes
against that migrated schema. PR #20 shipped code that read 039/040 columns
(``queries.deleted_at`` / ``queries.edited_at`` / ``documents.edited_at``) that
never got applied to prod → ``UndefinedColumn`` 500s. This gate asserts those
paths return 2xx-not-500 AND (the real enforcer) that the drift columns/tables
actually exist in the migrated schema.

LLM-key-free by construction: no ``POST /query`` (paid generation) and no
``/auth/demo-login``. Only read paths + writes that touch the 039/040 columns
without invoking the agent pipeline.
"""
from __future__ import annotations

import uuid

import pytest

from tests._migrations import apply_all_migrations
from tests.integration.conftest import GATE_CLIENT_EMAIL, GATE_CLIENT_ID

pytestmark = pytest.mark.deploygate


# --- direct-SQL seed helpers (write to the real migrated DB) -----------------


def _seed_query(conn, *, answer: str = "seed answer") -> str:
    """Insert one live ``queries`` row for the gate tenant; return its id."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO queries
                (client_id, user_email, question, module, status, final_answer)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (GATE_CLIENT_ID, GATE_CLIENT_EMAIL, "Is GST payable?", "research",
             "completed", answer),
        )
        query_id = cur.fetchone()[0]
    conn.commit()
    return str(query_id)


def _seed_document(conn, *, doc_type: str = "advice_memo") -> str:
    """Insert one ``documents`` row for the gate tenant; return its id."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO documents
                (client_id, document_type, title, content_md, status)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (GATE_CLIENT_ID, doc_type, "Seed memo", "# Seed body", "draft"),
        )
        document_id = cur.fetchone()[0]
    conn.commit()
    return str(document_id)


def _seed_firm_client(conn, *, name: str = "Acme Pty Ltd") -> str:
    """Insert one ``firm_clients`` row for the gate tenant; return its id."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO firm_clients (client_id, name)
            VALUES (%s, %s)
            RETURNING id
            """,
            (GATE_CLIENT_ID, name),
        )
        firm_client_id = cur.fetchone()[0]
    conn.commit()
    return str(firm_client_id)


# --- read-path endpoint gates (200-not-500) ----------------------------------


def test_query_history_reads_ok(authed_client):
    """GET /query -> QueriesRepo.list_recent (reads queries.edited_at/deleted_at,
    the 040 drift columns)."""
    resp = authed_client.get("/query")
    assert resp.status_code != 500
    assert resp.status_code == 200


def test_query_sessions_reads_ok(authed_client):
    resp = authed_client.get("/query/sessions")
    assert resp.status_code != 500
    assert resp.status_code == 200


def test_documents_list_reads_ok(authed_client):
    """GET /documents -> DocumentsRepo.list_for_client (reads documents.edited_at,
    the 040 drift column)."""
    resp = authed_client.get("/documents")
    assert resp.status_code != 500
    assert resp.status_code == 200


def test_knowledge_graph_reads_ok(authed_client):
    """GET /knowledge/graph -> KnowledgeIngestRepo.graph_metadata (filters
    queries.deleted_at, the 040 drift column)."""
    resp = authed_client.get("/knowledge/graph")
    assert resp.status_code != 500
    assert resp.status_code == 200


def test_engagements_list_reads_ok(authed_client):
    """GET /engagements -> EngagementsRepo.list_for_client (reads the 039
    engagements table)."""
    resp = authed_client.get("/engagements")
    assert resp.status_code != 500
    assert resp.status_code == 200


def test_health_reads_ok(authed_client):
    resp = authed_client.get("/health")
    assert resp.status_code != 500
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] == "connected"


# --- CRUD write-path gates (touch 039/040 columns, 2xx-not-500) --------------


def test_create_engagement_write_ok(authed_client, _migrated_db):
    """POST /engagements -> EngagementsRepo.create writes the 039 engagements
    table (+ increments firm_clients.next_engagement_seq, added by 039)."""
    firm_client_id = _seed_firm_client(_migrated_db, name=f"FC {uuid.uuid4()}")
    resp = authed_client.post(
        "/engagements",
        json={"firm_client_id": firm_client_id, "description": "FY25 tax advice"},
    )
    assert resp.status_code != 500
    assert resp.status_code == 201
    body = resp.json()
    assert body["firm_client_id"] == firm_client_id
    assert body["engagement_number"] == 1


def test_edit_query_writes_edited_at(authed_client, _migrated_db):
    """PATCH /query/{id} -> QueriesRepo.update sets queries.edited_at (040)."""
    query_id = _seed_query(_migrated_db)
    resp = authed_client.patch(
        f"/query/{query_id}", json={"final_answer": "Edited answer body."}
    )
    assert resp.status_code != 500
    assert resp.status_code == 200
    # Confirm the 040 column was actually written server-side.
    with _migrated_db.cursor() as cur:
        cur.execute("SELECT edited_at FROM queries WHERE id = %s", (query_id,))
        edited_at = cur.fetchone()[0]
    _migrated_db.commit()
    assert edited_at is not None


def test_soft_delete_query_writes_deleted_at(authed_client, _migrated_db):
    """DELETE /query/{id} -> QueriesRepo.delete sets queries.deleted_at (040)."""
    query_id = _seed_query(_migrated_db)
    resp = authed_client.delete(f"/query/{query_id}")
    assert resp.status_code != 500
    assert resp.status_code == 200
    with _migrated_db.cursor() as cur:
        cur.execute("SELECT deleted_at FROM queries WHERE id = %s", (query_id,))
        deleted_at = cur.fetchone()[0]
    _migrated_db.commit()
    assert deleted_at is not None


def test_edit_document_writes_edited_at(authed_client, _migrated_db):
    """PATCH /documents/{id} -> DocumentsRepo.update sets documents.edited_at
    (040)."""
    document_id = _seed_document(_migrated_db)
    resp = authed_client.patch(
        f"/documents/{document_id}",
        json={"title": "Renamed memo", "content_md": "# New body"},
    )
    assert resp.status_code != 500
    assert resp.status_code == 200
    with _migrated_db.cursor() as cur:
        cur.execute("SELECT edited_at, title FROM documents WHERE id = %s", (document_id,))
        edited_at, title = cur.fetchone()
    _migrated_db.commit()
    assert edited_at is not None
    assert title == "Renamed memo"


# --- schema drift enforcers (the real guarantee, independent of degradation) --


def _column_exists(conn, table: str, column: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s AND column_name = %s",
            (table, column),
        )
        found = cur.fetchone() is not None
    conn.commit()
    return found


def _table_exists(conn, table: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = %s",
            (table,),
        )
        found = cur.fetchone() is not None
    conn.commit()
    return found


def test_schema_has_drift_columns(_migrated_db):
    """Direct-SQL drift enforcer: the 039/040/041 objects the prod code reads
    MUST exist in the migrated schema. This — not endpoint-200 — is what catches
    an unapplied migration, because the read-path degradation returns 200 even
    on an un-migrated DB.
    """
    # 040 columns.
    assert _column_exists(_migrated_db, "queries", "deleted_at")
    assert _column_exists(_migrated_db, "queries", "edited_at")
    assert _column_exists(_migrated_db, "documents", "edited_at")
    # 039 table.
    assert _table_exists(_migrated_db, "engagements")
    # 041 objects.
    assert _table_exists(_migrated_db, "document_templates")
    assert _column_exists(_migrated_db, "documents", "ato_letter_type")


def test_full_migration_sequence_applied(_migrated_db):
    """The gate must apply the EXACT expected file sequence through 041 — so a
    dropped/skipped migration (e.g. 041) fails here, not just 039/040.

    Applied against a throwaway connection (its own scratch schema) so it does
    not disturb the session-scoped ``_migrated_db`` state used by the other
    tests.
    """
    import os

    import psycopg2

    from tests._migrations import _migrations_dir
    from tests.integration.conftest import _ensure_auth_role_stub

    expected = sorted(p.name for p in _migrations_dir().glob("*.sql"))

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        with conn.cursor() as cur:
            scratch = "gate_seq_check"
            cur.execute(f"DROP SCHEMA IF EXISTS {scratch} CASCADE;")
            cur.execute(f"CREATE SCHEMA {scratch};")
            # Route object creation into the scratch schema; keep public (with
            # its already-created extensions) on the path so ``vector`` /
            # ``gen_random_uuid`` resolve.
            cur.execute(f"SET search_path TO {scratch}, public;")
            _ensure_auth_role_stub(cur)
        conn.commit()
        applied = apply_all_migrations(conn)
        with conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {scratch} CASCADE;")
        conn.commit()
    finally:
        conn.close()

    assert applied == expected
    assert applied[-1] == "046_query_sessions_attribution.sql"
    assert len(applied) == 46
