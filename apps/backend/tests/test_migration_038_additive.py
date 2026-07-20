"""Phase 1: migration 038 must be additive-only.

Reads the raw SQL of ``038_annotations.sql`` and asserts every statement is one
of: ``CREATE TABLE``, ``CREATE INDEX``, ``ALTER TABLE ... ENABLE ROW LEVEL
SECURITY`` (RLS enable on the new table), or ``CREATE POLICY`` — the same shape
as the additive table-creation migration 037. There must be no ``ALTER``/``DROP``
of any *existing* table (the only ``ALTER TABLE`` allowed is enabling RLS on the
brand-new ``annotations`` table), so applying this migration cannot rewrite or
break existing data. No DB is touched.
"""
from __future__ import annotations

from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "supabase"
    / "migrations"
    / "038_annotations.sql"
)

NEW_TABLE = "annotations"


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
    assert stmts, "migration 038 has no statements"
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


def test_creates_the_new_annotations_table_with_client_id():
    create = next(
        (s for s in _statements() if s.upper().startswith("CREATE TABLE")), None
    )
    assert create is not None, "migration 038 must create a table"
    assert NEW_TABLE in create, "must create the annotations table"
    lower = create.lower()
    # Per-client table: the client_id column + FK is the tenant boundary.
    assert "client_id" in lower, "annotations must have a client_id column"
    assert "references clients(id)" in lower, "client_id must FK to clients(id)"


def test_polymorphic_target_and_thread_shape():
    create = next(s for s in _statements() if s.upper().startswith("CREATE TABLE"))
    lower = create.lower()
    # target_type CHECK is the single extension point for future surfaces.
    assert "check (target_type in ('query_answer','document'))" in lower
    assert "check (author_kind in ('reviewer','user'))" in lower
    # threads cascade-delete replies via the parent self-FK.
    assert "parent_id" in lower
    assert "references annotations(id) on delete cascade" in lower
    # target_id is polymorphic and must NOT be a foreign key.
    assert "target_id" in lower


def test_index_on_client_target():
    body = " ".join(_statements()).lower()
    assert "on annotations (client_id, target_type, target_id)" in body
    assert "on annotations (parent_id)" in body


def test_rls_mirrors_service_role_policy():
    body = " ".join(_statements())
    assert "ENABLE ROW LEVEL SECURITY" in body.upper()
    assert "service_role_full_access" in body
    assert "auth.role() = 'service_role'" in body
