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
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg2
import pytest

from tests.integration.conftest import _ensure_auth_role_stub

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
_BASE_URL = os.environ.get("DATABASE_URL", "")
# Isolated database for this module so its per-scenario `DROP SCHEMA public
# CASCADE` can never wipe the schema out from under test_deploy_gate.py's
# session-scoped _migrated_db (both would otherwise target the same DB, and
# cross-module pytest ordering in CI is not guaranteed). Set by _isolated_db.
_MIGRATION_URL = ""
_SELFTEST_DB = "taxflow_runner_selftest"


def _swap_db_name(url: str, dbname: str) -> str:
    """Return ``url`` with its database (path) replaced by ``dbname``."""
    parsed = urlparse(url)
    return urlunparse(parsed._replace(path=f"/{dbname}"))


@pytest.fixture(scope="module", autouse=True)
def _isolated_db():
    """Create a throwaway database for the runner self-test and point
    ``_MIGRATION_URL`` at it, so this module never touches the gate's DB."""
    global _MIGRATION_URL
    if not _BASE_URL or shutil.which("psql") is None:
        yield  # the per-test guard will skip; nothing to set up
        return
    try:
        admin = psycopg2.connect(_BASE_URL)
    except psycopg2.OperationalError:
        yield  # unreachable DB; per-test guard skips
        return
    try:
        admin.autocommit = True
        with admin.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{_SELFTEST_DB}" WITH (FORCE)')
            cur.execute(f'CREATE DATABASE "{_SELFTEST_DB}"')
    finally:
        admin.close()
    _MIGRATION_URL = _swap_db_name(_BASE_URL, _SELFTEST_DB)
    yield
    _MIGRATION_URL = ""
    admin = psycopg2.connect(_BASE_URL)
    try:
        admin.autocommit = True
        with admin.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{_SELFTEST_DB}" WITH (FORCE)')
    finally:
        admin.close()


def _expected_file_count() -> int:
    return len(list(_MIGRATIONS_DIR.glob("*.sql")))


def _reset_public_schema() -> None:
    """Drop + recreate ``public`` and drop the runner's ledger schema so each
    scenario starts from a clean, un-migrated database (on the isolated DB)."""
    conn = psycopg2.connect(_MIGRATION_URL)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS public CASCADE;")
            cur.execute("CREATE SCHEMA public;")
            cur.execute("DROP SCHEMA IF EXISTS taxflow_internal CASCADE;")
            # The RLS-policy migrations reference auth.role(); stub it so the
            # runner's CREATE POLICY DDL parses. Reuse the conditional helper so
            # this works on both CI's bare Postgres (creates it) and a local
            # Supabase stack (function already exists, owned by supabase_admin).
            _ensure_auth_role_stub(cur)
    finally:
        conn.close()


def _run_script(*args: str, extra_env: dict | None = None):
    """Invoke the real shell runner with MIGRATION_DATABASE_URL set.

    ``extra_env`` merges additional environment variables (e.g. a MIGRATIONS_DIR
    override pointing at a scratch dir of test migrations).
    """
    env = dict(os.environ)
    env["MIGRATION_DATABASE_URL"] = _MIGRATION_URL
    if extra_env:
        env.update(extra_env)
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
    if shutil.which("psql") is None:
        pytest.skip(
            "psql (postgresql-client) not installed; the shell runner needs it. "
            "CI installs it in the test-backend job."
        )
    # The root tests/conftest.py always sets DATABASE_URL via setdefault, so we
    # can't gate on it being unset — probe connectivity instead. CI points it at
    # a live pgvector service; a sandbox/local run without a reachable Postgres
    # skips cleanly so the full suite stays green.
    if not _BASE_URL:
        if os.environ.get("CI"):
            pytest.fail("DATABASE_URL not set under CI; the runner self-test must run.")
        pytest.skip("DATABASE_URL not set; runner self-test needs a real Postgres.")
    try:
        psycopg2.connect(_BASE_URL).close()
    except psycopg2.OperationalError as exc:
        # In CI (GitHub Actions sets CI=true) the runner self-test MUST run
        # against the live pgvector service — an unreachable DB is a hard failure
        # so a broken URL/service can't make the deploy-critical runner green.
        if os.environ.get("CI"):
            pytest.fail(
                "Runner self-test could not reach the Postgres at DATABASE_URL under CI: "
                f"{exc}"
            )
        pytest.skip(f"No reachable Postgres at DATABASE_URL for the runner self-test: {exc}")


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

    # 2. Wipe the ledger AND drop the >040-created objects so the DB genuinely
    #    reflects the prod rollout state: schema applied through 040, nothing
    #    after that applied yet. (Applying everything in step 1 was only to
    #    satisfy the bootstrap preflight that the ≤040 objects exist.) 042 is a
    #    pure idempotent data backfill (no DDL), so only 041's, 043's and 044's
    #    schema objects need dropping here.
    conn = psycopg2.connect(_MIGRATION_URL)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS taxflow_internal CASCADE;")
            cur.execute("DROP TABLE IF EXISTS document_templates CASCADE;")
            cur.execute("ALTER TABLE documents DROP COLUMN IF EXISTS ato_letter_type;")
            cur.execute("ALTER TABLE queries DROP COLUMN IF EXISTS created_by_user_id;")
            cur.execute("ALTER TABLE documents DROP COLUMN IF EXISTS created_by_user_id;")
            cur.execute("ALTER TABLE engagements DROP COLUMN IF EXISTS created_by_user_id;")
            cur.execute("DROP TABLE IF EXISTS users CASCADE;")
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
    """(d) A migration whose SQL fails PART-WAY THROUGH rolls back its already-
    succeeded DDL AND its ledger insert (nothing recorded, non-zero exit).

    To actually prove transactional rollback (not just that a single failing
    statement did nothing), the broken migration first runs a VALID
    ``CREATE TABLE gate_broken`` and only THEN hits an invalid statement. Because
    the runner applies each file with ``--single-transaction``, the successful
    CREATE must be rolled back too — so ``gate_broken`` must not exist afterward.
    """
    _reset_public_schema()

    scratch = tmp_path / "migrations"
    scratch.mkdir()
    (scratch / "001_ok.sql").write_text("CREATE TABLE gate_ok (id int PRIMARY KEY);\n")
    # Broken: a VALID create-table that succeeds, followed by an invalid statement
    # in the same file. The whole file runs in one transaction, so the successful
    # gate_broken create must roll back when the second statement errors.
    (scratch / "002_broken.sql").write_text(
        "CREATE TABLE gate_broken (id int PRIMARY KEY);\n"
        "CREATE TABLE gate_broken_ref (id int REFERENCES nonexistent_table(id));\n"
    )

    result = _run_script(extra_env={"MIGRATIONS_DIR": str(scratch)})

    # The broken file must fail the run.
    assert result.returncode != 0, (
        "runner should exit non-zero on a broken migration; "
        f"stdout={result.stdout} stderr={result.stderr}"
    )

    # The broken migration's DDL and ledger insert must both be rolled back:
    # gate_broken (a statement that SUCCEEDED before the failure) must not exist,
    # and 002 must not be recorded.
    conn = psycopg2.connect(_MIGRATION_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = 'gate_broken'"
            )
            assert cur.fetchone() is None, (
                "a statement that succeeded inside the failed migration was not "
                "rolled back — the file is not applied atomically"
            )
            cur.execute(
                "SELECT count(*) FROM taxflow_internal.applied_migrations "
                "WHERE version = '002'"
            )
            assert cur.fetchone()[0] == 0, "broken migration was recorded in the ledger"
    finally:
        conn.close()
