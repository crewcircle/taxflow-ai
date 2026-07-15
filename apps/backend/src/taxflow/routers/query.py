"""
Query router. Handles research queries through the full agent pipeline.
All endpoints require valid Supabase JWT (enforced by auth middleware).
"""
import asyncio
import json
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from taxflow.db import get_db, get_supabase_client
from taxflow.middleware.auth import get_current_client
from taxflow.middleware.trial_gate import check_trial_gate, increment_usage
from taxflow.services import answer_cache
from taxflow.services.agents import verify as verify_mod
from taxflow.services.agents.research import ResearchAgent
from taxflow.services.agents.verify import VerifyAgent
from taxflow.services.knowledge.embedder import embed

router = APIRouter(prefix="/query", tags=["query"])
agent = ResearchAgent()
verifier = VerifyAgent()


class QueryRequest(BaseModel):
    question: str
    module: str = "research"


class FeedbackRequest(BaseModel):
    rating: str  # "up" | "down"
    note: str | None = None


async def _maybe_verify(
    question: str,
    client_id: str,
    answer: str,
    citations: list[dict],
    confidence: float,
    embedding: list[float] | None = None,
) -> tuple[str, list[dict], dict | None, str | None]:
    """Run the gated verify pass + optional single corrective pass (B2 + C3).

    Returns (answer, citations, verification, caveat). Verification is None when
    the gate decided the answer wasn't risky enough to verify. When verification
    flags the answer, we surface a caveat and (if CORRECTIVE_PASS_ENABLED) run
    exactly ONE corrective regeneration — never a loop.
    """
    from taxflow.config import settings

    if not verify_mod.should_verify(confidence, citations, answer):
        return answer, citations, None, None

    model = verify_mod.verify_model_for(confidence, citations, answer)
    try:
        verification = await verifier.run(
            draft=answer, citations=citations, question=question, model=model
        )
    except Exception as e:  # noqa: BLE001 - verification must not break the response
        return answer, citations, {"overall_status": "parse_error", "issues": [], "error": str(e)}, None

    if not verify_mod.needs_correction(verification):
        return answer, citations, verification, None

    caveat = verify_mod.build_caveat(verification)

    # ONE bounded corrective pass (no loop): regenerate with the issues appended.
    if settings.CORRECTIVE_PASS_ENABLED:
        try:
            corrected = await agent.regenerate_with_feedback(
                question=question,
                client_id=client_id,
                issues=verification.get("issues", []),
                embedding=embedding,
            )
            verification["corrective_pass"] = True
            return corrected["answer"], corrected["citations"], verification, caveat
        except Exception:  # noqa: BLE001 - keep original answer if the retry fails
            verification["corrective_pass"] = False

    return answer, citations, verification, caveat


@router.get("")
async def list_queries(client=Depends(get_current_client), db=Depends(get_db)):
    """Recent query history for the sidebar - newest first."""
    result = (
        db.table("queries")
        .select(
            "id, question, status, model_used, confidence_score, verification_result, client_ref, "
            "context_note, topic_tag, created_at"
        )
        .eq("client_id", client["id"])
        .order("created_at", desc=True)
        .limit(50)
        .execute()
    )
    return result.data


@router.post("")
async def submit_query(
    body: QueryRequest,
    client=Depends(get_current_client),
    _trial=Depends(check_trial_gate),
    db=Depends(get_db),
):
    start = time.time()

    # Task B3: check the per-client DB-backed answer cache before running the
    # pipeline. A hit skips OpenAI embed + Anthropic generation entirely. The key
    # includes the client_id and knowledge_version, so an ingest invalidates and
    # one client never sees another's answer.
    cached = await answer_cache.get_cached_answer(client["id"], body.question)
    if cached is not None:
        query_id = await asyncio.to_thread(_persist_cached_query, db, client, body, cached, start)
        await increment_usage(client["id"], "queries")
        return {
            "query_id": query_id,
            "answer": cached["answer"],
            "citations": cached["citations"],
            "confidence": cached["confidence"],
            "model_used": cached["model_used"],
            "cached": True,
        }

    # Auth (get_current_client) and the trial gate (check_trial_gate) run as
    # Depends and MUST fully pass before this body executes, so the paid OpenAI
    # embed below can never fire for an invalid-token (401) or expired/capped
    # trial (402) request. Once past the gate, overlap the embed with the
    # queries-row insert (Task A4): both are independent I/O, so gather them and
    # await the embedding just before the vector search inside agent.run().
    def _insert_query_row() -> str:
        row = (
            db.table("queries")
            .insert(
                {
                    "client_id": client["id"],
                    "user_email": client["email"],
                    "question": body.question,
                    "module": body.module,
                    "status": "processing",
                }
            )
            .execute()
        )
        return row.data[0]["id"]

    embedding, query_id = await asyncio.gather(
        embed(body.question),
        asyncio.to_thread(_insert_query_row),
    )

    try:
        result = await agent.run(
            question=body.question, client_id=client["id"], embedding=embedding
        )

        # Task B2/C3: gate the verify pass and feed its output back into the
        # stored answer (caveat + one bounded corrective pass).
        answer, citations, verification, caveat = await _maybe_verify(
            question=body.question,
            client_id=client["id"],
            answer=result["answer"],
            citations=result["citations"],
            confidence=result["confidence"],
            embedding=embedding,
        )
        stored_answer = f"{answer}\n\n{caveat}" if caveat else answer

        update = {
            "status": "completed",
            "final_answer": stored_answer,
            "citations": citations,
            "confidence_score": result["confidence"],
            "model_used": result["model_used"],
            "input_tokens": result["input_tokens"],
            "output_tokens": result["output_tokens"],
            "cache_read_input_tokens": result.get("cache_read_input_tokens"),
            "cache_creation_input_tokens": result.get("cache_creation_input_tokens"),
            "wall_time_ms": int((time.time() - start) * 1000),
            "completed_at": "now()",
        }
        if verification is not None:
            update["verification_result"] = verification
        db.table("queries").update(update).eq("id", query_id).execute()

        await increment_usage(client["id"], "queries")

        # Task B3: cache the completed answer for this client (only when the
        # verify pass did not flag a correction — never cache a flagged answer).
        if verification is None or not caveat:
            await answer_cache.store_answer(
                client["id"],
                body.question,
                {
                    "answer": stored_answer,
                    "citations": citations,
                    "confidence": result["confidence"],
                    "model_used": result["model_used"],
                },
            )

        return {
            "query_id": query_id,
            "answer": stored_answer,
            "citations": citations,
            "confidence": result["confidence"],
            "model_used": result["model_used"],
        }

    except Exception as e:
        db.table("queries").update({"status": "failed", "error_message": str(e)}).eq("id", query_id).execute()
        raise HTTPException(status_code=500, detail=f"Query failed: {e}") from e


def _persist_cached_query(db, client, body: QueryRequest, cached: dict, start: float) -> str:
    """Insert a completed queries row for a cache hit so history + metrics still
    reflect the served answer (marked model_used='cache')."""
    row = (
        db.table("queries")
        .insert(
            {
                "client_id": client["id"],
                "user_email": client["email"],
                "question": body.question,
                "module": body.module,
                "status": "completed",
                "final_answer": cached["answer"],
                "citations": cached["citations"],
                "confidence_score": cached["confidence"],
                "model_used": "cache",
                "wall_time_ms": int((time.time() - start) * 1000),
                "completed_at": "now()",
            }
        )
        .execute()
    )
    return row.data[0]["id"]


@router.get("/stream")
async def stream_query(
    question: str,
    client_ref: str | None = None,
    client=Depends(get_current_client),
    _trial=Depends(check_trial_gate),
):
    """Server-Sent Events stream of the research -> verify pipeline.

    Emits: {"type": "token", ...} while the answer streams, then
    {"type": "final", "citations": [...], "query_id": ...} - this raw research
    answer is what's shown and stored as-is, not rewritten into a formal memo
    (that reformatting only happens on demand when saving as an advice_memo
    document). Then an async {"type": "verification", "status": ...,
    "issues": [...]} event checked against this same answer.
    """
    db = get_supabase_client()

    # As in POST /query: auth + trial gate (Depends) have already passed before
    # this body runs, so the paid embed cannot fire for a 401/402 request. Overlap
    # the embed with the queries-row insert (Task A4) and reuse the single vector
    # for both global and firm retrieval inside run_stream().
    def _insert_query_row() -> str:
        row = (
            db.table("queries")
            .insert(
                {
                    "client_id": client["id"],
                    "user_email": client["email"],
                    "question": question,
                    "module": "research",
                    "status": "processing",
                    "client_ref": client_ref,
                }
            )
            .execute()
        )
        return row.data[0]["id"]

    embedding, query_id = await asyncio.gather(
        embed(question),
        asyncio.to_thread(_insert_query_row),
    )

    start = time.time()

    async def generate():
        answer_parts: list[str] = []
        citations: list[dict] = []
        final_meta: dict = {}

        async for event in agent.run_stream(
            question=question, client_id=client["id"], embedding=embedding
        ):
            if event["type"] == "token":
                answer_parts.append(event["text"])
                yield f"data: {json.dumps(event)}\n\n"
            elif event["type"] == "final":
                citations = event["citations"]
                final_meta = event
                # The client only needs citations + query_id in the final event.
                yield f"data: {json.dumps({'type': 'final', 'citations': citations, 'query_id': query_id})}\n\n"

        final_answer = final_meta.get("answer") or "".join(answer_parts)
        confidence = final_meta.get("confidence", 0.0)

        # Task B2/C3: gate the verify pass in the stream path too, feeding its
        # output back (caveat + one bounded corrective pass) instead of running
        # Sonnet on every answer.
        answer, citations, verification, caveat = await _maybe_verify(
            question=question,
            client_id=client["id"],
            answer=final_answer,
            citations=citations,
            confidence=confidence,
            embedding=embedding,
        )
        stored_answer = f"{answer}\n\n{caveat}" if caveat else answer

        # Task C5: persist model_used/confidence/tokens/wall_time on the stream
        # path (previously only POST /query stored these), plus the B1 cache
        # tokens on both paths.
        update = {
            "status": "completed",
            "final_answer": stored_answer,
            "citations": citations,
            "confidence_score": confidence,
            "model_used": final_meta.get("model_used"),
            "input_tokens": final_meta.get("input_tokens"),
            "output_tokens": final_meta.get("output_tokens"),
            "cache_read_input_tokens": final_meta.get("cache_read_input_tokens"),
            "cache_creation_input_tokens": final_meta.get("cache_creation_input_tokens"),
            "wall_time_ms": int((time.time() - start) * 1000),
            "completed_at": "now()",
        }
        if verification is not None:
            update["verification_result"] = verification
        db.table("queries").update(update).eq("id", query_id).execute()
        await increment_usage(client["id"], "queries")

        # Task B3: cache the streamed answer unless the verify pass flagged it.
        if verification is None or not caveat:
            await answer_cache.store_answer(
                client["id"],
                question,
                {
                    "answer": stored_answer,
                    "citations": citations,
                    "confidence": confidence,
                    "model_used": final_meta.get("model_used"),
                },
            )

        verification_event = verification or {"overall_status": "not_verified", "issues": []}
        yield f"data: {json.dumps({'type': 'verification', **verification_event})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/{query_id}/feedback")
async def submit_feedback(
    query_id: str,
    body: FeedbackRequest,
    client=Depends(get_current_client),
    db=Depends(get_db),
):
    """Capture thumbs up/down (+ optional note) on a query result (Task C5).

    Enforces that query_id belongs to the requesting client before writing, so
    one client can neither attach feedback to nor probe another client's query.
    """
    if body.rating not in ("up", "down"):
        raise HTTPException(status_code=422, detail="rating must be 'up' or 'down'")

    owned = (
        db.table("queries")
        .select("id")
        .eq("id", query_id)
        .eq("client_id", client["id"])
        .execute()
    )
    if not owned.data:
        raise HTTPException(status_code=404, detail="Query not found")

    row = (
        db.table("query_feedback")
        .insert(
            {
                "query_id": query_id,
                "client_id": client["id"],
                "rating": body.rating,
                "note": body.note,
            }
        )
        .execute()
    )
    return {"id": row.data[0]["id"], "query_id": query_id, "rating": body.rating}


# Must stay below /stream - FastAPI matches routes in declaration order, and this
# wildcard path param would otherwise swallow /query/stream as query_id="stream".
@router.get("/{query_id}")
async def get_query(query_id: str, client=Depends(get_current_client), db=Depends(get_db)):
    result = db.table("queries").select("*").eq("id", query_id).eq("client_id", client["id"]).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Query not found")
    return result.data[0]
