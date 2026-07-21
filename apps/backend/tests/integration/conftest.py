"""Fixtures for the deploy gate (``deploygate`` marker).

These fixtures stand up the FULL migrated schema on a real Postgres and expose
an authenticated ``TestClient`` whose requests hit that real DB (only
``get_current_client`` is overridden; ``get_db`` stays real). The gate then
proves the shipped read/CRUD query shapes match the migrated schema — the exact
class of drift that took prod down when migrations 039/040 never applied.

Requires ``DATABASE_URL`` to point at a throwaway/local Postgres: the
``_migrated_db`` fixture runs ``DROP SCHEMA public CASCADE`` for deterministic
re-runs, so it must NEVER point at a real database.
"""
from __future__ import annotations

import os

import psycopg2
import pytest
from fastapi.testclient import TestClient

from tests._migrations import apply_all_migrations

# Fixed tenant used across the gate. Seeded once into ``clients`` and injected
# as the authenticated identity via the ``get_current_client`` override.
GATE_CLIENT_ID = "00000000-0000-0000-0000-000000000001"
GATE_CLIENT_EMAIL = "gate@example.com.au"
GATE_CLIENT_BUSINESS_NAME = "Deploy Gate Firm"


def _ensure_auth_role_stub(cur) -> None:
    """Ensure ``auth.role()`` exists so the 14 RLS-policy migrations' CREATE
    POLICY DDL parses on bare Postgres.

    On CI's bare ``pgvector`` image neither the ``auth`` schema nor the function
    exists and we connect as superuser, so we create both. On a local Supabase
    stack the schema + function already exist (owned by ``supabase_admin``, which
    our ``postgres`` role cannot replace) — so only create what is missing rather
    than CREATE OR REPLACE, which would raise a permission error. Either way the
    function resolves to ``'service_role'`` for the gate (RLS is bypassed anyway
    on a superuser connection).
    """
    cur.execute(
        "SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'auth' AND p.proname = 'role'"
    )
    if cur.fetchone() is not None:
        return
    cur.execute("CREATE SCHEMA IF NOT EXISTS auth;")
    cur.execute(
        "CREATE OR REPLACE FUNCTION auth.role() RETURNS text "
        "LANGUAGE sql AS $$ SELECT 'service_role'::text $$;"
    )


def _refuse_if_looks_like_real_data(conn) -> None:
    """Hard stop before ``DROP SCHEMA public CASCADE`` if ``clients`` already
    holds any row besides the gate fixture itself.

    This fixture is only safe against an empty/throwaway Postgres — the
    docstring below has said so since it was written, but nothing enforced it.
    A local run with ``DATABASE_URL`` accidentally resolved to a real
    database (e.g. a Doppler ``dev`` config that turns out to alias the same
    instance as ``prd``) silently wiped production data this way at least
    once. An empty table or one only ever seeded by a prior gate run is fine
    and stays fast/idempotent; anything else aborts loudly instead of
    dropping it.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'clients'"
        )
        if cur.fetchone() is None:
            return  # Nothing created yet — genuinely empty DB, nothing to lose.
        cur.execute("SELECT count(*) FROM public.clients WHERE id != %s", (GATE_CLIENT_ID,))
        other_rows = cur.fetchone()[0]
    if other_rows > 0:
        pytest.fail(
            "REFUSING TO RUN THE DEPLOY GATE: DATABASE_URL's `clients` table already "
            f"has {other_rows} row(s) besides the gate fixture ({GATE_CLIENT_ID}). This "
            "fixture runs `DROP SCHEMA public CASCADE` and would destroy them. "
            "DATABASE_URL must point at a throwaway/local Postgres — it looks like it is "
            "pointing at a real database (dev or prod) instead. STOP and fix DATABASE_URL "
            "(or the Doppler config it comes from) before running this again."
        )


@pytest.fixture(scope="session")
def _migrated_db():
    """Yield a psycopg2 connection to a Postgres with ALL migrations applied.

    Steps (session-scoped, run once):
      1. Connect to ``DATABASE_URL``.
      2. Refuse to proceed if the target already has non-gate client data (see
         ``_refuse_if_looks_like_real_data`` — the actual enforcement of the
         "throwaway Postgres only" contract this fixture has always assumed).
      3. ``DROP SCHEMA public CASCADE; CREATE SCHEMA public;`` for deterministic
         re-runs (a leftover schema from a prior run must not shadow drift).
      4. Stub ``auth.role()`` so the 14 RLS-policy migrations' ``CREATE POLICY``
         DDL parses on bare Postgres. RLS is bypassed anyway (superuser conn) —
         the gate proves schema + query shape, NOT tenant isolation.
      5. Apply every migration; yield the connection; close on teardown.
    """
    dsn = os.environ["DATABASE_URL"]
    try:
        conn = psycopg2.connect(dsn)
    except psycopg2.OperationalError as exc:
        # The root tests/conftest.py always sets a dummy DATABASE_URL via
        # setdefault, so we can't gate on it being unset. Instead we probe
        # connectivity. In CI (GitHub Actions always sets CI=true) the gate MUST
        # run against the live pgvector service, so an unreachable DB is a hard
        # failure — otherwise a bad URL, credentials error, or service regression
        # would make the deploy gate silently green. Only a local/sandbox run
        # (CI unset) skips cleanly so `uv run pytest tests/` stays green.
        if os.environ.get("CI"):
            pytest.fail(
                "Deploy gate could not reach the Postgres at DATABASE_URL under CI "
                f"— the gate must not be skipped in CI: {exc}"
            )
        pytest.skip(f"No reachable Postgres at DATABASE_URL for the deploy gate: {exc}")
    try:
        _refuse_if_looks_like_real_data(conn)
        with conn.cursor() as cur:
            # Deterministic re-runs: wipe and recreate the public schema.
            cur.execute("DROP SCHEMA IF EXISTS public CASCADE;")
            cur.execute("CREATE SCHEMA public;")
            _ensure_auth_role_stub(cur)
        conn.commit()
        apply_all_migrations(conn)
        yield conn
    finally:
        conn.close()


@pytest.fixture(scope="module")
def authed_client(_migrated_db):
    """A ``TestClient`` authenticated as the fixed gate tenant.

    Seeds one ``clients`` row (fixed UUID) directly, overrides only
    ``get_current_client`` (so requests carry the tenant identity without a real
    JWT), and leaves ``get_db`` un-overridden so every request hits the real
    migrated DB via the psycopg2 pool.
    """
    with _migrated_db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO clients (id, business_name, business_type, email, suburb, state)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (
                GATE_CLIENT_ID,
                GATE_CLIENT_BUSINESS_NAME,
                "accounting",
                GATE_CLIENT_EMAIL,
                "Sydney",
                "NSW",
            ),
        )
    _migrated_db.commit()

    from taxflow.main import app
    from taxflow.middleware.auth import get_current_client

    def _fake_current_client() -> dict:
        return {
            "id": GATE_CLIENT_ID,
            "email": GATE_CLIENT_EMAIL,
            "business_name": GATE_CLIENT_BUSINESS_NAME,
            "subscription_status": "active",
        }

    app.dependency_overrides[get_current_client] = _fake_current_client
    # NOTE: build the client WITHOUT the ``with`` context manager so the app
    # ``lifespan`` does NOT run — it would fire the startup embedding-dimension
    # probe (a paid OpenAI call) and start the scheduler, neither of which the
    # LLM-key-free gate needs. This mirrors the top-level ``tests/conftest.py``
    # ``client`` fixture.
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
