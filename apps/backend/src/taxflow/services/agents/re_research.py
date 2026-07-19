"""Feedback-triggered async re-research worker (Task C2).

A user thumbs-down WITH a note enqueues a ``re_research_jobs`` row (see
``routers/query.py::submit_feedback``). This worker drains that queue on a
scheduler interval (leader-guarded so only one uvicorn worker runs it) and
re-runs the answer with the user's stated issue and a WIDENED retrieval pool,
then notifies the user via the ``notifications`` table.

Reviewer/verify flags are NOT handled here — they run synchronously in the
inline corrective pass (Task C3). Only user thumbs-down-with-note is async, so
``feedback_id`` is a clean idempotency key.

Concurrency / at-most-once
--------------------------
``claim_next`` atomically flips a due ``queued`` row to ``running`` under
``FOR UPDATE SKIP LOCKED`` and the scheduler leader guard ensures a single
worker drains at a time. Transient failures ``requeue`` with backoff until
``RE_RESEARCH_MAX_ATTEMPTS`` is reached, after which the job is terminal
``failed`` and a ``re_research_failed`` notification is emitted.

The repositories are SYNCHRONOUS (psycopg2), so every repo call is wrapped in
``asyncio.to_thread`` — this worker itself is async (it awaits the embedder and
the research agent). This module talks ONLY to repos/ports + the research agent;
it imports no external SDK, keeping the ports-and-adapters gate green.
"""

from __future__ import annotations

import asyncio
import logging

from taxflow.config import settings
from taxflow.services.agents.graph import research_agent
from taxflow.services.knowledge.embedder import embed

logger = logging.getLogger(__name__)


async def run_one_job(db, job: dict) -> None:
    """Re-research a single claimed job, then mark it done / requeue / fail.

    ``job`` is the row returned by ``claim_next`` (already ``status='running'``
    with ``attempts`` incremented). On success the query is rewritten with the
    improved answer and an ``answer_improved`` notification is inserted. On
    failure the job is requeued (attempts left) or marked ``failed`` (+ a
    ``re_research_failed`` notification) at the attempt ceiling.
    """
    client_id = job["client_id"]
    query_id = job["query_id"]
    job_id = job["id"]

    try:
        answer_row = await asyncio.to_thread(
            db.queries.get_answer_for_client, client_id, query_id
        )
        if not answer_row:
            # The query vanished (e.g. deleted). Terminal — nothing to re-run.
            await asyncio.to_thread(
                db.re_research_jobs.mark, job_id, "failed",
                {"error_message": "query not found"},
            )
            await asyncio.to_thread(
                db.queries.set_re_research_status, client_id, query_id, "failed"
            )
            return

        question = answer_row["question"]

        # CRITICAL (resolves M1): load the client row and thread it into
        # regenerate_with_feedback. _build_steering derives the firm profile,
        # firm_style voice, session steering and the active_modules source-type
        # hint from this dict — passing client=None would silently drop ALL firm
        # voice/profile steering on the async answer.
        client = await asyncio.to_thread(db.clients.get_by_id, client_id)

        # The user's stated issue is the single verifier-style issue driving the
        # corrective regeneration. Only "issue" is known here; the other fields
        # are left blank (the agent tolerates empty claim/source/correction).
        note = job.get("feedback_note") or ""
        issues = [
            {
                "issue": note,
                "claim": "",
                "source_says": "",
                "suggested_correction": "",
            }
        ]

        embedding = await embed(question)

        result = await research_agent.regenerate_with_feedback(
            question,
            client_id,
            issues=issues,
            embedding=embedding,
            client=client,
            session_id=answer_row.get("session_id"),
            client_ref=answer_row.get("client_ref"),
            widen=True,
        )

        # Merge the re-retrieval marker onto the agent's trace so the persisted
        # trace records that this answer was rewritten by the feedback-triggered
        # worker (re_retrieved=True, reason="feedback_triggered").
        trace = dict(result.get("trace") or {})
        trace["re_retrieval"] = {
            "fired": True,
            "reason": "feedback_triggered",
            "detail": None,
        }

        await asyncio.to_thread(
            db.queries.update,
            client_id,
            query_id,
            {
                "final_answer": result["answer"],
                "citations": result["citations"],
                "confidence_score": result["confidence"],
                "model_used": result["model_used"],
                "trace": trace,
            },
        )
        await asyncio.to_thread(db.re_research_jobs.mark, job_id, "done")
        await asyncio.to_thread(
            db.queries.set_re_research_status, client_id, query_id, "done"
        )
        await asyncio.to_thread(
            db.notifications.insert,
            {
                "client_id": client_id,
                "kind": "answer_improved",
                "query_id": query_id,
                "title": "Your answer was improved",
                "body": "We re-researched your question based on your feedback. "
                "Open it to see the updated answer.",
            },
        )
    except Exception as exc:  # noqa: BLE001
        attempts = job.get("attempts", 0)
        if attempts < settings.RE_RESEARCH_MAX_ATTEMPTS:
            # Transient failure with attempts left: requeue with backoff so
            # claim_next picks it up again after the delay.
            logger.warning(
                "re-research job %s failed (attempt %s), requeueing: %s",
                job_id, attempts, exc,
            )
            await asyncio.to_thread(
                db.re_research_jobs.requeue,
                job_id,
                str(exc),
                settings.RE_RESEARCH_BACKOFF_SECONDS,
            )
        else:
            logger.error(
                "re-research job %s failed permanently after %s attempts: %s",
                job_id, attempts, exc,
            )
            await asyncio.to_thread(
                db.re_research_jobs.mark, job_id, "failed",
                {"error_message": str(exc)},
            )
            await asyncio.to_thread(
                db.queries.set_re_research_status, client_id, query_id, "failed"
            )
            await asyncio.to_thread(
                db.notifications.insert,
                {
                    "client_id": client_id,
                    "kind": "re_research_failed",
                    "query_id": query_id,
                    "title": "Re-research could not be completed",
                    "body": "We were unable to re-research your question. "
                    "The original answer is unchanged.",
                },
            )


async def drain(limit: int = 10) -> int:
    """Drain up to ``limit`` due jobs, one at a time. Returns the count run.

    Loops ``claim_next`` (each call atomically claims one due job) until there
    are no more due jobs or ``limit`` is reached. Runs on the scheduler interval
    behind the leader guard, so at most one worker drains concurrently.
    """
    from taxflow.providers import get_relational_data

    db = get_relational_data()
    ran = 0
    while ran < limit:
        job = await asyncio.to_thread(db.re_research_jobs.claim_next)
        if job is None:
            break
        await run_one_job(db, job)
        ran += 1
    return ran
