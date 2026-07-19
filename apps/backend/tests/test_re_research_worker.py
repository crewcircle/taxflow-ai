"""Task C2: feedback-triggered async re-research worker (run_one_job / drain)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import taxflow.services.agents.re_research as rr


def _db():
    db = MagicMock()
    db.queries.get_answer_for_client.return_value = {
        "question": "Is a ute a car for FBT?",
        "final_answer": "old answer",
        "citations": [],
        "session_id": "sess-1",
        "client_ref": "Acme",
    }
    db.clients.get_by_id.return_value = {
        "id": "client-1",
        "business_type": "SMSF",
        "firm_style": "formal",
    }
    return db


def _job(**overrides):
    job = {
        "id": "job-1",
        "client_id": "client-1",
        "query_id": "q1",
        "feedback_note": "You cited the wrong section",
        "attempts": 1,
    }
    job.update(overrides)
    return job


@pytest.mark.asyncio
async def test_run_one_job_success_threads_client_and_note():
    db = _db()

    regen = AsyncMock(
        return_value={
            "answer": "improved answer",
            "citations": [{"citation": "s 8-1"}],
            "confidence": 0.9,
            "model_used": "sonnet",
            "trace": {"retrieval": {"chunks_considered": 5}, "generation": {"model": "sonnet"}},
        }
    )

    with patch.object(rr, "embed", new=AsyncMock(return_value=[0.0] * 1536)), patch.object(
        rr.research_agent, "regenerate_with_feedback", new=regen
    ):
        await rr.run_one_job(db, _job())

    # The client row was loaded and threaded in (NOT None) — firm steering kept.
    db.clients.get_by_id.assert_called_once_with("client-1")
    regen.assert_awaited_once()
    kwargs = regen.await_args.kwargs
    assert kwargs["client"] == db.clients.get_by_id.return_value
    assert kwargs["client"] is not None
    assert kwargs["widen"] is True
    assert kwargs["session_id"] == "sess-1"
    # C4: client_ref from the loaded query row is threaded through so the async
    # regenerate uses the same engagement-context memos + trace.session.client_ref.
    assert kwargs["client_ref"] == "Acme"

    # issues built FROM the feedback_note.
    issues = kwargs["issues"]
    assert issues == [
        {
            "issue": "You cited the wrong section",
            "claim": "",
            "source_says": "",
            "suggested_correction": "",
        }
    ]

    # Query updated with improved answer + a feedback_triggered re_retrieval trace.
    db.queries.update.assert_called_once()
    cid, qid, fields = db.queries.update.call_args.args
    assert cid == "client-1"
    assert qid == "q1"
    assert fields["final_answer"] == "improved answer"
    assert fields["trace"]["re_retrieval"] == {
        "fired": True,
        "reason": "feedback_triggered",
        "detail": None,
    }

    db.re_research_jobs.mark.assert_called_once_with("job-1", "done")
    db.queries.set_re_research_status.assert_called_once_with("client-1", "q1", "done")

    # Success notification.
    db.notifications.insert.assert_called_once()
    note = db.notifications.insert.call_args.args[0]
    assert note["kind"] == "answer_improved"
    assert note["query_id"] == "q1"
    assert note["client_id"] == "client-1"


@pytest.mark.asyncio
async def test_run_one_job_requeues_on_transient_failure():
    db = _db()

    with patch.object(rr, "embed", new=AsyncMock(return_value=[0.0] * 1536)), patch.object(
        rr.research_agent, "regenerate_with_feedback",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        # attempts=1 < MAX (3) -> requeue, not terminal fail.
        await rr.run_one_job(db, _job(attempts=1))

    db.re_research_jobs.requeue.assert_called_once()
    args = db.re_research_jobs.requeue.call_args.args
    assert args[0] == "job-1"
    assert "boom" in args[1]
    db.re_research_jobs.mark.assert_not_called()
    db.notifications.insert.assert_not_called()


@pytest.mark.asyncio
async def test_run_one_job_fails_at_max_attempts():
    db = _db()

    with patch.object(rr, "embed", new=AsyncMock(return_value=[0.0] * 1536)), patch.object(
        rr.research_agent, "regenerate_with_feedback",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        # attempts=3 == MAX -> terminal failed + failure notification.
        await rr.run_one_job(db, _job(attempts=3))

    db.re_research_jobs.requeue.assert_not_called()
    db.re_research_jobs.mark.assert_called_once()
    mark_args = db.re_research_jobs.mark.call_args.args
    assert mark_args[0] == "job-1"
    assert mark_args[1] == "failed"
    db.queries.set_re_research_status.assert_called_once_with("client-1", "q1", "failed")

    db.notifications.insert.assert_called_once()
    note = db.notifications.insert.call_args.args[0]
    assert note["kind"] == "re_research_failed"


@pytest.mark.asyncio
async def test_drain_loops_claim_next_until_none():
    db = _db()
    # Two jobs then None.
    db.re_research_jobs.claim_next.side_effect = [_job(id="j1"), _job(id="j2"), None]

    with patch("taxflow.providers.get_relational_data", return_value=db), patch.object(
        rr, "run_one_job", new=AsyncMock()
    ) as run_mock:
        ran = await rr.drain(limit=10)

    assert ran == 2
    assert run_mock.await_count == 2


@pytest.mark.asyncio
async def test_drain_respects_limit():
    db = _db()
    db.re_research_jobs.claim_next.side_effect = [_job(id="j1"), _job(id="j2"), _job(id="j3")]

    with patch("taxflow.providers.get_relational_data", return_value=db), patch.object(
        rr, "run_one_job", new=AsyncMock()
    ) as run_mock:
        ran = await rr.drain(limit=2)

    assert ran == 2
    assert run_mock.await_count == 2
    # Stopped at the limit; claim_next called at most limit times.
    assert db.re_research_jobs.claim_next.call_count == 2
