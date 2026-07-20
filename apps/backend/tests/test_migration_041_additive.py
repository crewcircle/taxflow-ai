"""Phase 5: migration 041 must be additive-only.

Reads the raw SQL of ``041_document_templates.sql`` and asserts every statement
is one of: ``CREATE TABLE`` (the new ``document_templates`` table),
``CREATE [UNIQUE] INDEX``, ``ALTER TABLE ... ENABLE ROW LEVEL SECURITY`` (RLS on
the new table), ``CREATE POLICY``, or the single additive
``ALTER TABLE documents ADD COLUMN ato_letter_type text`` (nullable, no
backfill). There must be no ``DROP``/``ALTER COLUMN``/``ALTER TYPE`` and no
touching of the ``documents_document_type_check`` CHECK — so applying this
migration cannot rewrite or break existing data. No DB is touched.

Mirrors ``test_migration_037_additive.py``.
"""
from __future__ import annotations

from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "supabase"
    / "migrations"
    / "041_document_templates.sql"
)

NEW_TABLE = "document_templates"


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
    assert stmts, "migration 041 has no statements"
    for stmt in stmts:
        upper = stmt.upper()
        is_create_table = upper.startswith("CREATE TABLE")
        is_create_index = upper.startswith("CREATE INDEX") or upper.startswith(
            "CREATE UNIQUE INDEX"
        )
        is_rls_enable = upper.startswith("ALTER TABLE") and "ENABLE ROW LEVEL SECURITY" in upper
        is_policy = upper.startswith("CREATE POLICY")
        is_add_column = upper.startswith("ALTER TABLE") and "ADD COLUMN" in upper
        assert (
            is_create_table or is_create_index or is_rls_enable or is_policy or is_add_column
        ), f"unexpected statement in additive migration: {stmt}"


def test_no_drop_alter_column_or_alter_type():
    for stmt in _statements():
        upper = stmt.upper()
        assert "DROP" not in upper, f"DROP forbidden: {stmt}"
        assert "ALTER COLUMN" not in upper, f"ALTER COLUMN forbidden: {stmt}"
        assert "ALTER TYPE" not in upper, f"ALTER TYPE forbidden: {stmt}"


def test_alter_table_targets_limited_to_new_table_and_additive_add_column():
    """The only ALTER TABLE statements allowed are: enabling RLS on the new
    document_templates table, and the single additive ADD COLUMN on documents."""
    for stmt in _statements():
        upper = stmt.upper()
        if not upper.startswith("ALTER TABLE"):
            continue
        is_rls = "ENABLE ROW LEVEL SECURITY" in upper and NEW_TABLE in stmt
        is_add_col = "ADD COLUMN" in upper and "DOCUMENTS" in upper
        assert is_rls or is_add_col, f"unexpected ALTER TABLE: {stmt}"


def test_documents_check_constraint_untouched():
    body = " ".join(_statements()).lower()
    assert "documents_document_type_check" not in body
    assert "document_type" not in body, "must not touch the document_type CHECK"


def test_add_column_is_nullable_additive():
    add = next(
        (s for s in _statements() if "ADD COLUMN" in s.upper()), None
    )
    assert add is not None, "migration must add the ato_letter_type column"
    upper = add.upper()
    assert "ATO_LETTER_TYPE" in upper
    assert "DOCUMENTS" in upper
    # Nullable additive column: no NOT NULL, no DEFAULT backfill.
    assert "NOT NULL" not in upper, f"ADD COLUMN must be nullable: {add}"
    assert "DEFAULT" not in upper, f"ADD COLUMN must not backfill a default: {add}"


def test_creates_new_table_with_client_id():
    create = next(
        (s for s in _statements() if s.upper().startswith("CREATE TABLE")), None
    )
    assert create is not None, "migration 041 must create a table"
    assert NEW_TABLE in create, "must create the document_templates table"
    # Tenant-scoped: MUST have a client_id column (RLS gives zero isolation).
    assert "client_id" in create.lower(), "document_templates must have a client_id column"


def test_unique_index_on_client_id_template_key():
    body = " ".join(_statements()).lower()
    assert "create unique index" in body
    assert "(client_id, template_key)" in body, "unique index on (client_id, template_key)"


def test_rls_mirrors_service_role_policy():
    body = " ".join(_statements())
    assert "ENABLE ROW LEVEL SECURITY" in body.upper()
    assert "service_role_full_access" in body
    assert "auth.role() = 'service_role'" in body
