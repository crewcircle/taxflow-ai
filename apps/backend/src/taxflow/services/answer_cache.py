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

All DB access goes through the QueryCacheRepo (Task B4); the synchronous
psycopg2 calls run in a thread so the event loop is not blocked.
"""
import asyncio
import re

from taxflow.config import settings
from taxflow.providers import get_relational_data

_WS = re.compile(r"\s+")


def normalise_question(question: str) -> str:
    """Deterministic normalisation for the cache key: lowercase, collapse
    whitespace, strip surrounding punctuation. Pure function of the text."""
    text = (question or "").strip().lower()
    text = _WS.sub(" ", text)
    return text.strip(" \t\n?.!")


def _get_knowledge_version_sync() -> int:
    return get_relational_data().query_cache.current_knowledge_version()


async def get_knowledge_version() -> int:
    return await asyncio.to_thread(_get_knowledge_version_sync)


def bump_knowledge_version() -> int:
    """Increment the knowledge_version token (called after an ingest run).

    Bumping the token makes every worker compute a new cache key, so all existing
    cached answers become unreachable at once. Returns the new version.
    """
    return get_relational_data().query_cache.bump_knowledge_version()


def _get_sync(client_id: str, question_norm: str, version: int) -> dict | None:
    return get_relational_data().query_cache.get_cached(question_norm, client_id, version)


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
    get_relational_data().query_cache.put_cached(
        {
            "client_id": client_id,
            "question_norm": question_norm,
            "knowledge_version": version,
            "result": result,
        }
    )


async def store_answer(client_id: str, question: str, result: dict) -> None:
    """Cache a freshly computed result for this client + question."""
    if not settings.ANSWER_CACHE_ENABLED:
        return
    version = await get_knowledge_version()
    question_norm = normalise_question(question)
    await asyncio.to_thread(_store_sync, client_id, question_norm, version, result)


async def count_prior_asks(client_id: str, question: str) -> int:
    """Count this client's already-completed queries with the same normalised
    question text (Firm Knowledge suggestion trigger: prompt to save an
    answer once a client has asked essentially the same thing before).

    The SQL (in QueryCacheRepo) mirrors normalise_question's logic (lowercase,
    collapse whitespace, strip surrounding punctuation) so a match is a genuine
    repeat, not a formatting difference. Called before the current query's row
    is marked 'completed', so it never counts itself.
    """
    question_norm = normalise_question(question)
    return await asyncio.to_thread(
        get_relational_data().query_cache.count_prior_asks, client_id, question_norm
    )
