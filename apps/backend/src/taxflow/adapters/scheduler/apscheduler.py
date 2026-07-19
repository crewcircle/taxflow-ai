"""APScheduler adapter implementing :class:`SchedulerPort`.

This is the ONE place that constructs the periodic-job scheduler and registers
the three cron jobs. The public ``taxflow.scheduler`` functions are thin
delegators to :func:`taxflow.providers.get_scheduler_port`.

Multi-worker leader guard
-------------------------
Production runs uvicorn with ``--workers 2``: each worker is a separate process
with its own ``AsyncIOScheduler``, so without a guard every cron job would fire
once per worker (double execution). We wrap each job callable in a Postgres
advisory-lock leader guard: before running, a worker tries to grab a
session-level advisory lock keyed by a stable bigint per job id. Only the worker
that wins the lock runs the job body; the loser logs and skips. The lock is
always released and the connection closed in a ``finally`` block, even if the
job raises.

The guard uses a DEDICATED short-lived ``psycopg2.connect`` (NOT the shared
request pool from :func:`taxflow.db.get_pg_conn`) so a long-running job never
holds a pooled connection hostage for the duration of the job.
"""

from __future__ import annotations

import functools
import logging

import psycopg2
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from taxflow.config import settings

logger = logging.getLogger(__name__)


# Stable advisory-lock keys, one per job id. Session-level advisory locks share a
# single 64-bit key space, so these must be distinct and stable across workers
# and deploys. Hand-assigned constants (arbitrary but fixed) keep them readable.
_LOCK_KEYS: dict[str, int] = {
    "kb_ingestion": 7_310_001,
    "regulatory_monitor": 7_310_002,
    "demo_reset": 7_310_003,
    "re_research_drain": 7_310_004,
}


def _leader_guard(job_id: str, func):
    """Wrap ``func`` so only the worker holding job ``job_id``'s advisory lock runs it.

    Opens a dedicated short-lived psycopg2 connection, tries the advisory lock,
    and either skips (lock held elsewhere) or runs ``func`` and releases the lock
    + closes the connection in a ``finally`` block.
    """
    lock_key = _LOCK_KEYS[job_id]

    @functools.wraps(func)
    async def _guarded(*args, **kwargs):
        conn = psycopg2.connect(settings.DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s)", (lock_key,))
                acquired = cur.fetchone()[0]
            if not acquired:
                logger.info(
                    "scheduler job %s: another worker holds lock, skipping", job_id
                )
                return None
            try:
                return await _maybe_await(func, *args, **kwargs)
            finally:
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))
        finally:
            conn.close()

    return _guarded


async def _maybe_await(func, *args, **kwargs):
    """Call ``func`` and await it if it returns an awaitable (jobs may be sync or async)."""
    import inspect

    result = func(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


class APSchedulerAdapter:
    """SchedulerPort adapter backed by an :class:`AsyncIOScheduler`."""

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()

    def _register_jobs(self) -> None:
        from taxflow.services.agents.re_research import drain as re_research_drain
        from taxflow.services.demo_reset import reset_demo_data
        from taxflow.services.knowledge.ingest import run_all
        from taxflow.services.regulatory_monitor import check_feeds

        # Daily knowledge base delta scrape, 2am Sydney time (UTC+10/11 -> 16:00 UTC)
        self._scheduler.add_job(
            _leader_guard("kb_ingestion", run_all),
            "cron",
            hour=16,
            minute=0,
            id="kb_ingestion",
            replace_existing=True,
        )
        # Regulatory monitor weekly, Monday 6am Sydney time (UTC+10/11 -> 20:00 UTC Sunday)
        self._scheduler.add_job(
            _leader_guard("regulatory_monitor", check_feeds),
            "cron",
            day_of_week="sun",
            hour=20,
            minute=0,
            id="regulatory_monitor",
            replace_existing=True,
        )
        # Demo account cleanup, 3am Sydney time (17:00 UTC)
        self._scheduler.add_job(
            _leader_guard("demo_reset", reset_demo_data),
            "cron",
            hour=17,
            minute=0,
            id="demo_reset",
            replace_existing=True,
        )
        # Feedback-triggered re-research queue drain (Task C2): poll the
        # re_research_jobs queue on a short interval. Leader-guarded so only one
        # worker drains at a time; claim_next + FOR UPDATE SKIP LOCKED make the
        # claim itself concurrency-safe.
        self._scheduler.add_job(
            _leader_guard("re_research_drain", re_research_drain),
            "interval",
            seconds=settings.RE_RESEARCH_POLL_SECONDS,
            id="re_research_drain",
            replace_existing=True,
        )

    def start(self) -> None:
        if not self._scheduler.running:
            self._register_jobs()
            self._scheduler.start()

    def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def is_running(self) -> bool:
        return self._scheduler.running
