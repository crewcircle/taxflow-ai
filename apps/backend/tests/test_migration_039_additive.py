"""Phase 2: migration 039 must be additive-only.

Reads the raw SQL of ``039_engagements.sql`` and asserts every statement is one
of: ``CREATE TABLE`` / ``CREATE INDEX`` / ``CREATE UNIQUE INDEX`` /
``ALTER TABLE ... ENABLE ROW LEVEL SECURITY`` (RLS enable on the new table) /
``CREATE POLICY`` / ``ALTER TABLE ... ADD COLUMN`` (additive column adds, the
precedent 012/019 set). There must be no ``DROP`` / ``ALTER COLUMN`` /
``ALTER TYPE`` and no ``ADD COLUMN ... NOT NULL`` without a ``DEFAULT`` on an
existing table, so applying this migration cannot rewrite or break existing rows
(or the Phase 1 annotations). No DB is touched.
"""
from __future__ import annotations

from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "supabase"
    / "migrations"
    / "039_engagements.sql"
)

NEW_TABLE = "engagements"


def _statements() -> list[str]:
    """Return non-comment, non-blank SQL statements (split on ';')."""
    lines = []
    for raw in MIGRATION.read_text().splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("--"):
            continue
        lines.append(stripped)
    body = " ".join(lines)
    return [s.strip() for s in body.split(";") if s.strip()]


def test_migration_file_exists():
    assert MIGRATION.exists(), f"missing migration file: {MIGRATION}"


def test_only_additive_statements():
    stmts = _statements()
    assert stmts, "migration 039 has no statements"
    for stmt in stmts:
        upper = stmt.upper()
        is_create_table = upper.startswith("CREATE TABLE")
        is_create_index = upper.startswith("CREATE INDEX")
        is_create_unique_index = upper.startswith("CREATE UNIQUE INDEX")
        is_rls_enable = upper.startswith("ALTER TABLE") and "ENABLE ROW LEVEL SECURITY" in upper
        is_policy = upper.startswith("CREATE POLICY")
        is_add_column = upper.startswith("ALTER TABLE") and "ADD COLUMN" in upper
        assert (
            is_create_table
            or is_create_index
            or is_create_unique_index
            or is_rls_enable
            or is_policy
            or is_add_column
        ), f"unexpected statement in additive migration: {stmt}"


def test_no_drop_or_destructive_alter():
    for stmt in _statements():
        upper = stmt.upper()
        assert "DROP" not in upper, f"DROP forbidden: {stmt}"
        assert "ALTER COLUMN" not in upper, f"ALTER COLUMN forbidden: {stmt}"
        assert "ALTER TYPE" not in upper, f"ALTER TYPE forbidden: {stmt}"


def test_add_columns_to_existing_tables_are_additive():
    """ADD COLUMN on an existing table must be nullable OR carry a DEFAULT, so
    the add never rewrites existing rows with a NOT-NULL-without-default fill."""
    for stmt in _statements():
        upper = stmt.upper()
        if not (upper.startswith("ALTER TABLE") and "ADD COLUMN" in upper):
            continue
        # RLS-enable ALTER on the new table is handled separately.
        if "ENABLE ROW LEVEL SECURITY" in upper:
            continue
        if "NOT NULL" in upper:
            assert "DEFAULT" in upper, (
                f"ADD COLUMN NOT NULL on existing table needs a DEFAULT: {stmt}"
            )


def test_creates_engagements_with_both_ids_not_null():
    create = next(
        (s for s in _statements() if s.upper().startswith("CREATE TABLE")), None
    )
    assert create is not None, "migration 039 must create a table"
    assert NEW_TABLE in create, "must create the engagements table"
    lower = create.lower()
    # Both the tenant FK (client_id) and the end-client FK (firm_client_id) are
    # NOT NULL: an engagement is always attributed to a real end-client.
    assert "client_id" in lower and "references clients(id)" in lower
    assert "firm_client_id" in lower and "references firm_clients(id)" in lower
    assert "client_id         uuid not null" in lower or "client_id uuid not null" in lower
    assert "firm_client_id    uuid not null" in lower or "firm_client_id uuid not null" in lower
    # description is NOT NULL (app layer applies a default when blank).
    assert "description       text not null" in lower or "description text not null" in lower


def test_unique_index_on_firm_client_and_number():
    body = " ".join(_statements()).lower()
    assert "create unique index" in body
    assert "on engagements (firm_client_id, engagement_number)" in body
    assert "on engagements (client_id, firm_client_id)" in body


def test_rls_mirrors_service_role_policy():
    body = " ".join(_statements())
    assert "ENABLE ROW LEVEL SECURITY" in body.upper()
    assert "service_role_full_access" in body
    assert "auth.role() = 'service_role'" in body


def test_engagement_id_added_to_queries_and_documents_nullable():
    stmts = _statements()
    for table in ("queries", "documents"):
        add = next(
            (
                s
                for s in stmts
                if s.upper().startswith("ALTER TABLE")
                and f" {table} " in f" {s.lower()} "
                and "add column engagement_id" in s.lower()
            ),
            None,
        )
        assert add is not None, f"engagement_id must be added to {table}"
        # Nullable: no NOT NULL on the additive link column.
        assert "not null" not in add.lower(), (
            f"engagement_id on {table} must be nullable: {add}"
        )


def test_next_engagement_seq_added_to_firm_clients_with_default_zero():
    stmts = _statements()
    add = next(
        (
            s
            for s in stmts
            if s.upper().startswith("ALTER TABLE")
            and "firm_clients" in s.lower()
            and "add column next_engagement_seq" in s.lower()
        ),
        None,
    )
    assert add is not None, "next_engagement_seq must be added to firm_clients"
    lower = add.lower()
    assert "default 0" in lower, f"next_engagement_seq must DEFAULT 0: {add}"
