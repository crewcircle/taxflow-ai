"""Automated test of the REAL ``scripts/apply_migrations.sh`` deploy runner.

The shell runner (built by Group A) is what actually applies migrations in
production, so the deploy-critical path must be validated in CI — not just the
Python ``apply_all_migrations`` helper. This test drives the actual script via
``subprocess`` against a throwaway Postgres schema.

The script is authored on a separate branch and merges alongside this test; if
it is not present yet (pre-merge), every test in this module skips gracefully.

Isolation: this module uses a DEDICATED throwaway database URL and drops/creates
its own ``public`` schema at the start of each scenario, so it never clobbers
the deploy gate's session-scoped ``_migrated_db`` state.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import psycopg2
import pytest

pytestmark = pytest.mark.deploygate

# repo root: tests/integration/test_apply_migrations.py
#   -> integration -> tests -> apps/backend -> apps -> <repo root>
_REPO_ROOT = Path(__file__).resolve().parents[4]
_SCRIPT = _REPO_ROOT / "scripts" / "apply_migrations.sh"
_MIGRATIONS_DIR = (
    Path(__file__).resolve().parents[2] / "supabase" / "migrations"
)

# The migration runner requires a session-scoped (port-5432-style) URL and
# hard-refuses a transaction-pooler URL on :6543. The local/CI Postgres is a
# direct connection, so DATABASE_URL is a valid MIGRATION_DATABASE_URL here.
_MIGRATION_URL = os.environ.get("DATABASE_URL", "")


def _expected_file_count() -> int:
    return len(list(_MIGRATIONS_DIR.glob("*.sql")))


def _reset_public_schema() -> None:
    """Drop + recreate ``public`` and drop the runner's ledger schema so each
    scenario starts from a clean, un-migrated database."""
    conn = psycopg2.connect(_MIGRATION_URL)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS public CASCADE;")
            cur.execute("CREATE SCHEMA public;")
            cur.execute("DROP SCHEMA IF EXISTS taxflow_internal CASCADE;")
            # The RLS-policy migrations reference auth.role(); stub it so the
            # runner's CREATE POLICY DDL parses on bare Postgres.
            cur.execute("CREATE SCHEMA IF NOT EXISTS auth;")
            cur.execute(
                "CREATE OR REPLACE FUNCTION auth.role() RETURNS text "
                "LANGUAGE sql AS $$ SELECT 'service_role'::text $$;"
            )
    finally:
        conn.close()


def _run_script(*args: str):
    """Invoke the real shell runner with MIGRATION_DATABASE_URL set."""
    env = dict(os.environ)
    env["MIGRATION_DATABASE_URL"] = _MIGRATION_URL
    return subprocess.run(
        ["bash", str(_SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_REPO_ROOT),
    )


def _ledger_count() -> int:
    conn = psycopg2.connect(_MIGRATION_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM taxflow_internal.applied_migrations"
            )
            return cur.fetchone()[0]
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _require_script_and_db():
    if not _SCRIPT.exists():
        pytest.skip(
            f"scripts/apply_migrations.sh not present yet ({_SCRIPT}); "
            "runner self-test will run once Group A's branch merges."
        )
    if not _MIGRATION_URL:
        pytest.skip("DATABASE_URL not set; runner self-test needs a real Postgres.")


def test_fresh_run_applies_all_and_records_ledger():
    """(a) A fresh run against a clean DB applies every file and records exactly
    one ledger row per migration."""
    _reset_public_schema()
    result = _run_script()
    assert result.returncode == 0, result.stderr
    assert _ledger_count() == _expected_file_count()


def test_second_run_is_noop():
    """(b) A second run applies nothing ("No pending migrations", no new rows)."""
    _reset_public_schema()
    first = _run_script()
    assert first.returncode == 0, first.stderr
    count_after_first = _ledger_count()

    second = _run_script()
    assert second.returncode == 0, second.stderr
    assert "No pending migrations" in (second.stdout + second.stderr)
    assert _ledger_count() == count_after_first


def test_bootstrap_through_040_then_applies_only_041():
    """(c) Bootstrap-through-040 then a normal run applies only 041.

    Approach: the script's ``--mark-applied-through`` runs a schema preflight
    that requires the ≤040 objects to already exist, so we first apply the full
    schema normally (a real apply), then reset ONLY the ledger (keeping the
    schema) and mark 001–040 as applied. A subsequent normal run then finds only
    041 pending and applies it — proving the bootstrap-then-041 sequence the
    prod rollout depends on.
    """
    # 1. Apply everything so the ≤040 schema is genuinely present.
    _reset_public_schema()
    applied_all = _run_script()
    assert applied_all.returncode == 0, applied_all.stderr

    # 2. Wipe ONLY the ledger (schema stays) so the bootstrap preflight passes.
    conn = psycopg2.connect(_MIGRATION_URL)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS taxflow_internal CASCADE;")
    finally:
        conn.close()

    # 3. Bootstrap the ledger through 040 (no DDL re-run; preflight checks the
    #    ≤040 schema is present).
    boot = _run_script("--mark-applied-through", "040")
    assert boot.returncode == 0, boot.stderr
    assert _ledger_count() == 40

    # 4. A normal run now applies only the single pending file (041).
    final_run = _run_script()
    assert final_run.returncode == 0, final_run.stderr
    assert "041" in (final_run.stdout + final_run.stderr)
    assert _ledger_count() == _expected_file_count()


def test_broken_migration_rolls_back(tmp_path):
    """(d) A deliberately broken scratch migration rolls back its DDL AND its
    ledger insert (nothing recorded, non-zero exit).

    We can't drop a bad file into the shipped migrations dir, so we point the
    runner at a scratch dir (if it honours a MIGRATIONS_DIR override) OR fall
    back to asserting the runner exits non-zero and records nothing when the
    file fails. The scratch dir holds one valid + one broken migration.
    """
    _reset_public_schema()

    scratch = tmp_path / "migrations"
    scratch.mkdir()
    (scratch / "001_ok.sql").write_text("CREATE TABLE gate_ok (id int PRIMARY KEY);\n")
    # Broken: references a column/table that does not exist -> DDL error.
    (scratch / "002_broken.sql").write_text(
        "CREATE TABLE gate_broken (id int REFERENCES nonexistent_table(id));\n"
    )

    env = dict(os.environ)
    env["MIGRATION_DATABASE_URL"] = _MIGRATION_URL
    env["MIGRATIONS_DIR"] = str(scratch)
    result = subprocess.run(
        ["bash", str(_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_REPO_ROOT),
    )

    # The broken file must fail the run.
    assert result.returncode != 0, (
        "runner should exit non-zero on a broken migration; "
        f"stdout={result.stdout} stderr={result.stderr}"
    )

    # The broken migration's DDL and ledger insert must both be rolled back:
    # gate_broken must not exist, and 002 must not be recorded.
    conn = psycopg2.connect(_MIGRATION_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = 'gate_broken'"
            )
            assert cur.fetchone() is None, "broken migration DDL was not rolled back"
            cur.execute(
                "SELECT count(*) FROM taxflow_internal.applied_migrations "
                "WHERE version = '002'"
            )
            assert cur.fetchone()[0] == 0, "broken migration was recorded in the ledger"
    finally:
        conn.close()
