import threading
from contextlib import contextmanager
from functools import lru_cache

import psycopg2
import psycopg2.pool
from supabase import create_client, Client

from taxflow.config import settings

# --- Postgres connection pool -------------------------------------------------
# Historically every DB call opened a fresh raw connection to DATABASE_URL,
# paying a fresh TLS handshake + auth round trip per statement (a single /query
# opened three). We keep a lazily-created, thread-safe pool instead and borrow /
# return connections via get_pg_conn().
#
# Sizing: POOL_MAX_CONN is per-worker. Production runs 2 uvicorn workers (each a
# separate process with its own pool), so total connections to Supabase are
# roughly `POOL_MAX_CONN * workers`. The default (8) keeps 2 workers at ~16
# connections, comfortably under Supabase's direct-connection cap.
#
# Zero-code alternative (do NOT combine with this pool): point DATABASE_URL at
# Supabase's transaction pooler on port 6543, which pools server-side. We use an
# in-process pool here instead; using both would double-pool for no benefit.

_pool: psycopg2.pool.ThreadedConnectionPool | None = None
_pool_lock = threading.Lock()


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = psycopg2.pool.ThreadedConnectionPool(
                    settings.POOL_MIN_CONN,
                    settings.POOL_MAX_CONN,
                    settings.DATABASE_URL,
                )
    return _pool


@contextmanager
def get_pg_conn():
    """Borrow a pooled psycopg2 connection and return it in a finally block.

    The connection is always returned to the pool, even if the body raises. We
    roll back first so any open transaction is cleared and the connection goes
    back to the pool in a clean state (queries here are SELECT-only or commit
    explicitly, but a failed statement can still leave an aborted transaction).
    """
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
    finally:
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001 - never mask the original error on return
            pass
        pool.putconn(conn)


# --- Supabase client ----------------------------------------------------------


@lru_cache
def get_supabase_client() -> Client:
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


async def get_db() -> Client:
    return get_supabase_client()
