"""Task 3a-1: migration 036 must be additive-only.

Reads the raw SQL of ``036_production_quality_snapshots.sql`` and asserts it
only CREATEs a NEW table (plus its index + RLS policy) and never ALTERs or
DROPs an EXISTING table/column. The only ``ALTER TABLE`` permitted is the
``ENABLE ROW LEVEL SECURITY`` on the new table itself (mirrors mig 030); there
must be no ``ADD COLUMN``/``ALTER COLUMN``/``ALTER TYPE``/``DROP``. This guards
the rollback story: a purely additive new-table migration needs no reversal of
existing data. No DB is touched.
"""
from __future__ import annotations

from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "supabase"
    / "migrations"
    / "036_production_quality_snapshots.sql"
)

NEW_TABLE = "production_quality_snapshots"


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


def test_only_create_table_index_and_rls():
    stmts = _statements()
    assert stmts, "migration 036 has no statements"
    for stmt in stmts:
        upper = stmt.upper()
        assert (
            upper.startswith("CREATE TABLE")
            or upper.startswith("CREATE INDEX")
            or upper.startswith("CREATE POLICY")
            or upper.startswith("ALTER TABLE")  # only ENABLE ROW LEVEL SECURITY, checked below
        ), f"unexpected statement kind: {stmt}"
        if upper.startswith("ALTER TABLE"):
            assert "ENABLE ROW LEVEL SECURITY" in upper, f"ALTER TABLE must only enable RLS: {stmt}"


def test_no_drops_or_alters_of_existing_columns():
    for stmt in _statements():
        upper = stmt.upper()
        assert "DROP" not in upper, f"DROP forbidden: {stmt}"
        assert "ADD COLUMN" not in upper, f"ADD COLUMN forbidden (new table only): {stmt}"
        assert "ALTER COLUMN" not in upper, f"ALTER COLUMN forbidden: {stmt}"
        assert "ALTER TYPE" not in upper, f"ALTER TYPE forbidden: {stmt}"


def test_creates_the_new_snapshots_table():
    create = [s for s in _statements() if s.upper().startswith("CREATE TABLE")]
    assert len(create) == 1, "expected exactly one CREATE TABLE"
    assert NEW_TABLE in create[0], f"CREATE TABLE must target {NEW_TABLE}"


def test_new_table_has_required_columns():
    create = next(s for s in _statements() if s.upper().startswith("CREATE TABLE"))
    for col in (
        "window_start",
        "window_end",
        "baseline_start",
        "baseline_end",
        "metrics",
        "diff",
        "has_regressions",
        "created_at",
    ):
        assert col in create, f"missing column {col} in CREATE TABLE"
    # metrics is the one NOT NULL payload column; has_regressions defaults false.
    assert "metrics jsonb NOT NULL" in create
    assert "has_regressions boolean NOT NULL DEFAULT false" in create


def test_index_on_created_at_desc():
    idx = [s for s in _statements() if s.upper().startswith("CREATE INDEX")]
    assert idx, "expected a CREATE INDEX"
    assert any("created_at DESC" in s for s in idx), "index must be on (created_at DESC)"


def test_rls_mirrors_migration_030():
    stmts = _statements()
    assert any(
        s.upper().startswith("ALTER TABLE") and "ENABLE ROW LEVEL SECURITY" in s.upper()
        for s in stmts
    ), "must ENABLE ROW LEVEL SECURITY on the new table"
    assert any(
        s.upper().startswith("CREATE POLICY") and "service_role" in s for s in stmts
    ), "must add a service_role policy mirroring migration 030"
