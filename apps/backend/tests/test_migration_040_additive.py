"""Phase 3: migration 040 must be additive-only.

Reads the raw SQL of ``040_editable_content.sql`` and asserts every statement is
an ``ALTER TABLE ... ADD COLUMN`` on an existing table with a nullable column —
no ``DROP``, no ``ALTER COLUMN``, no ``ALTER TYPE``, no ``NOT NULL``/``DEFAULT``
that would rewrite existing rows. Applying this migration therefore cannot
rewrite or break existing data. No DB is touched.

Mirrors ``test_migration_037_additive.py`` for the additive ADD-COLUMN case
(037 is a new-table migration; 040 only adds nullable columns to existing
tables).
"""
from __future__ import annotations

from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "supabase"
    / "migrations"
    / "040_editable_content.sql"
)

EXPECTED_COLUMNS = {
    ("documents", "edited_at"),
    ("queries", "edited_at"),
    ("queries", "deleted_at"),
}


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


def test_only_additive_add_column_statements():
    stmts = _statements()
    assert stmts, "migration 040 has no statements"
    for stmt in stmts:
        upper = stmt.upper()
        assert upper.startswith("ALTER TABLE"), (
            f"only ALTER TABLE ... ADD COLUMN allowed: {stmt}"
        )
        assert "ADD COLUMN" in upper, f"only ADD COLUMN allowed: {stmt}"


def test_no_drop_or_destructive_alter():
    for stmt in _statements():
        upper = stmt.upper()
        assert "DROP" not in upper, f"DROP forbidden: {stmt}"
        assert "ALTER COLUMN" not in upper, f"ALTER COLUMN forbidden: {stmt}"
        assert "ALTER TYPE" not in upper, f"ALTER TYPE forbidden: {stmt}"


def test_columns_are_nullable_no_default():
    # Nullable + no default = no table rewrite / backfill of existing rows.
    for stmt in _statements():
        upper = stmt.upper()
        assert "NOT NULL" not in upper, f"columns must stay nullable: {stmt}"
        assert "DEFAULT" not in upper, f"no DEFAULT (would rewrite rows): {stmt}"


def test_adds_expected_editable_columns():
    body = " ".join(_statements()).lower()
    for table, column in EXPECTED_COLUMNS:
        assert f"alter table {table} add column {column} timestamptz" in body, (
            f"missing additive column {table}.{column}"
        )
