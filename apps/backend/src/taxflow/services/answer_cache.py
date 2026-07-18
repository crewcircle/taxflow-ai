"""Per-client DB-backed answer cache (Task B3).

Prod runs 2 uvicorn workers (separate processes), so an in-process answer cache
can neither share hits nor be invalidated atomically across workers. This cache
is backed by Postgres (query_cache table) instead:

  - Entries are keyed on (normalised question, client_id, knowledge_version).
  - knowledge/ingest.py bumps knowledge_version on every ingest, so all workers
    immediately compute the new key and old rows become unreachable — atomic
    invalidation with no cross-process signalling.
  - A short TTL (ANSWER_CACHE_TTL_SECONDS) is a backstop.
  - Client isolation is hard: the client_id is part of the key and RLS scopes the
    table to the service role. One client's answer is never served to another.

All DB access goes through the shared pool (get_pg_conn); psycopg2 calls run in a
thread so the event loop is not blocked.
"""
import asyncio
import json
import re

import psycopg2.extras

from taxflow.config import settings
from taxflow.db import get_pg_conn

_WS = re.compile(r"\s+")


def normalise_question(question: str) -> str:
    """Deterministic normalisation for the cache key: lowercase, collapse
    whitespace, strip surrounding punctuation. Pure function of the text."""
    text = (question or "").strip().lower()
    text = _WS.sub(" ", text)
    return text.strip(" \t\n?.!")


def _get_knowledge_version_sync() -> int:
    with get_pg_conn() as conn:
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT version FROM knowledge_version WHERE id = true")
            row = cur.fetchone()
            cur.close()
            return int(row[0]) if row else 1


async def get_knowledge_version() -> int:
    return await asyncio.to_thread(_get_knowledge_version_sync)


def bump_knowledge_version() -> int:
    """Increment the knowledge_version token (called after an ingest run).

    Bumping the token makes every worker compute a new cache key, so all existing
    cached answers become unreachable at once. Returns the new version.
    """
    with get_pg_conn() as conn:
        with conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE knowledge_version
                SET version = version + 1, updated_at = now()
                WHERE id = true
                RETURNING version
                """
            )
            row = cur.fetchone()
            cur.close()
            return int(row[0]) if row else 1


def _get_sync(client_id: str, question_norm: str, version: int) -> dict | None:
    with get_pg_conn() as conn:
        with conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                """
                SELECT result
                FROM query_cache
                WHERE client_id = %s
                  AND question_norm = %s
                  AND knowledge_version = %s
                  AND created_at > now() - (%s || ' seconds')::interval
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (client_id, question_norm, version, settings.ANSWER_CACHE_TTL_SECONDS),
            )
            row = cur.fetchone()
            cur.close()
            if not row:
                return None
            result = row["result"]
            return result if isinstance(result, dict) else json.loads(result)


async def get_cached_answer(client_id: str, question: str) -> dict | None:
    """Return a cached result dict for this client + question, or None on miss.

    Miss reasons: no row, stale (older than TTL), or knowledge_version bumped
    since it was cached (an ingest happened) — all handled by the key + TTL.
    """
    if not settings.ANSWER_CACHE_ENABLED:
        return None
    version = await get_knowledge_version()
    question_norm = normalise_question(question)
    return await asyncio.to_thread(_get_sync, client_id, question_norm, version)


def _store_sync(client_id: str, question_norm: str, version: int, result: dict) -> None:
    with get_pg_conn() as conn:
        with conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO query_cache (client_id, question_norm, knowledge_version, result)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (client_id, question_norm, knowledge_version)
                DO UPDATE SET result = EXCLUDED.result, created_at = now()
                """,
                (client_id, question_norm, version, json.dumps(result)),
            )
            cur.close()


async def store_answer(client_id: str, question: str, result: dict) -> None:
    """Cache a freshly computed result for this client + question."""
    if not settings.ANSWER_CACHE_ENABLED:
        return
    version = await get_knowledge_version()
    question_norm = normalise_question(question)
    await asyncio.to_thread(_store_sync, client_id, question_norm, version, result)


def _count_prior_asks_sync(client_id: str, question_norm: str) -> int:
    with get_pg_conn() as conn:
        with conn:
            cur = conn.cursor()
            cur.execute(
                r"""
                SELECT COUNT(*) FROM queries
                WHERE client_id = %s
                  AND status = 'completed'
                  AND btrim(regexp_replace(lower(btrim(question)), '\s+', ' ', 'g'), E' \t\n?.!') = %s
                """,
                (client_id, question_norm),
            )
            row = cur.fetchone()
            cur.close()
            return int(row[0]) if row else 0


async def count_prior_asks(client_id: str, question: str) -> int:
    """Count this client's already-completed queries with the same normalised
    question text (Firm Knowledge suggestion trigger: prompt to save an
    answer once a client has asked essentially the same thing before).

    Mirrors normalise_question's logic in SQL (lowercase, collapse whitespace,
    strip surrounding punctuation) so a match here is a genuine repeat, not a
    formatting difference. Called before the current query's row is marked
    'completed', so it never counts itself.
    """
    question_norm = normalise_question(question)
    return await asyncio.to_thread(_count_prior_asks_sync, client_id, question_norm)
