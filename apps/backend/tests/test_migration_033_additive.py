"""Task C1: migration 033 must be additive-only.

Reads the raw SQL of ``033_knowledge_chunk_hierarchy.sql`` and asserts every
statement is a plain ``ALTER TABLE ... ADD COLUMN`` — no ``NOT NULL``, no
``DEFAULT``, no ``DROP``/``ALTER COLUMN``/``ALTER TYPE`` that would rewrite or
break existing rows. This guards the rollback story: a purely additive-nullable
migration needs no reversal (flip the feature flag instead). No DB is touched.
"""
from __future__ import annotations

from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "supabase"
    / "migrations"
    / "033_knowledge_chunk_hierarchy.sql"
)

EXPECTED_COLUMNS = {
    "heading_path",
    "section_ref",
    "chunk_level",
    "parent_key",
    "parent_content",
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


def test_every_statement_is_add_column():
    stmts = _statements()
    assert stmts, "migration 033 has no statements"
    for stmt in stmts:
        upper = stmt.upper()
        assert upper.startswith("ALTER TABLE"), f"non-ALTER statement: {stmt}"
        assert "ADD COLUMN" in upper, f"statement is not ADD COLUMN: {stmt}"


def test_no_not_null_no_default():
    for stmt in _statements():
        upper = stmt.upper()
        assert "NOT NULL" not in upper, f"NOT NULL forbidden in additive migration: {stmt}"
        assert "DEFAULT" not in upper, f"DEFAULT forbidden in additive migration: {stmt}"


def test_no_drops_or_alters_of_existing_columns():
    for stmt in _statements():
        upper = stmt.upper()
        assert "DROP" not in upper, f"DROP forbidden: {stmt}"
        assert "ALTER COLUMN" not in upper, f"ALTER COLUMN forbidden: {stmt}"
        assert "ALTER TYPE" not in upper, f"ALTER TYPE forbidden: {stmt}"


def test_all_five_hierarchy_columns_added():
    added = set()
    for stmt in _statements():
        parts = stmt.split()
        # ... ADD COLUMN <name> <type>
        idx = [p.upper() for p in parts].index("COLUMN")
        added.add(parts[idx + 1])
    assert added == EXPECTED_COLUMNS
