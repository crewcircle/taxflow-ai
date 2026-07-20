"""Task 3a-0: migration 037 must be additive-only.

Reads the raw SQL of ``037_ops_notifications.sql`` and asserts every statement
is one of: ``CREATE TABLE``, ``CREATE INDEX``, ``ALTER TABLE ... ENABLE ROW
LEVEL SECURITY`` (RLS enable on the new table), or ``CREATE POLICY`` — the same
shape as the additive table-creation migration 030. There must be no
``ALTER``/``DROP`` of any *existing* table (the only ``ALTER TABLE`` allowed is
enabling RLS on the brand-new ``ops_notifications`` table), so applying this
migration cannot rewrite or break existing data. No DB is touched.

This mirrors ``test_migration_033_additive.py`` for the new-table case: the
existing per-client ``notifications`` table and its RLS stay untouched.
"""
from __future__ import annotations

from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "supabase"
    / "migrations"
    / "037_ops_notifications.sql"
)

NEW_TABLE = "ops_notifications"


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


def test_only_create_table_index_or_rls_statements():
    stmts = _statements()
    assert stmts, "migration 037 has no statements"
    for stmt in stmts:
        upper = stmt.upper()
        is_create_table = upper.startswith("CREATE TABLE")
        is_create_index = upper.startswith("CREATE INDEX")
        is_rls_enable = upper.startswith("ALTER TABLE") and "ENABLE ROW LEVEL SECURITY" in upper
        is_policy = upper.startswith("CREATE POLICY")
        assert is_create_table or is_create_index or is_rls_enable or is_policy, (
            f"unexpected statement in additive migration: {stmt}"
        )


def test_no_alter_or_drop_of_existing_tables():
    for stmt in _statements():
        upper = stmt.upper()
        assert "DROP" not in upper, f"DROP forbidden: {stmt}"
        assert "ALTER COLUMN" not in upper, f"ALTER COLUMN forbidden: {stmt}"
        assert "ALTER TYPE" not in upper, f"ALTER TYPE forbidden: {stmt}"
        # The only ALTER TABLE allowed is enabling RLS on the NEW table.
        if upper.startswith("ALTER TABLE"):
            assert "ENABLE ROW LEVEL SECURITY" in upper, f"non-RLS ALTER TABLE forbidden: {stmt}"
            assert NEW_TABLE in stmt, f"ALTER TABLE must target the new table only: {stmt}"


def test_creates_the_new_ops_table_without_client_id():
    create = next(
        (s for s in _statements() if s.upper().startswith("CREATE TABLE")), None
    )
    assert create is not None, "migration 037 must create a table"
    assert NEW_TABLE in create, "must create the ops_notifications table"
    # Ops-scoped: NO client_id column.
    assert "client_id" not in create.lower(), "ops_notifications must NOT have a client_id column"


def test_rls_mirrors_migration_030_service_role_policy():
    body = " ".join(_statements())
    assert "ENABLE ROW LEVEL SECURITY" in body.upper()
    assert "service_role_full_access" in body
    assert "auth.role() = 'service_role'" in body


def test_index_on_created_at_desc():
    body = " ".join(_statements()).lower()
    assert "created_at desc" in body, "must index (created_at DESC)"
