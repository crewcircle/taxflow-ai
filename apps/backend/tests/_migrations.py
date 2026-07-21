"""Apply every committed SQL migration to a real Postgres connection.

Used by the deploy gate (``tests/integration/``) to stand up the full schema on
CI's Postgres service (and a local Supabase stack) before exercising the
read/CRUD endpoints against it. This is the Python counterpart of the deploy
pipeline's ``scripts/apply_migrations.sh`` — the shell runner is what actually
runs in production; this helper is a lightweight in-test applier so the gate can
assert schema shape + query correctness without shelling out.

Every ``CREATE EXTENSION IF NOT EXISTS vector/pgcrypto`` in the migrations
succeeds here because CI connects as the ``postgres`` superuser and the
``pgvector/pgvector:pg16`` image (and the local Supabase image) ships both
extensions.
"""
from __future__ import annotations

from pathlib import Path


def _migrations_dir() -> Path:
    # tests/_migrations.py -> tests/ -> apps/backend/ -> apps/backend/supabase/migrations
    return Path(__file__).resolve().parent.parent / "supabase" / "migrations"


def apply_all_migrations(conn) -> list[str]:
    """Apply all ``NNN_*.sql`` migrations in numeric-prefix order to ``conn``.

    Each file's FULL text is executed via one ``cur.execute(sql_text)`` (psycopg2
    happily runs multi-statement scripts in a single call). A single
    ``conn.commit()`` at the end makes the whole schema visible. Returns the list
    of applied filenames (e.g. ``["001_clients.sql", ..., "041_document_templates.sql"]``)
    in the exact order they were applied, so callers can assert the sequence.
    """
    migrations_dir = _migrations_dir()
    applied: list[str] = []
    with conn.cursor() as cur:
        for path in sorted(migrations_dir.glob("*.sql")):
            sql_text = path.read_text()
            cur.execute(sql_text)
            applied.append(path.name)
    conn.commit()
    return applied
