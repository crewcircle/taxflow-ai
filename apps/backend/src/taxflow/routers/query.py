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
    # Task D3: an explicit per-conversation session id. The dashboard UI must mint
    # a fresh session_id (uuid) when the user starts a new conversation ("new
    # chat") and reuse the SAME session_id across every turn of that conversation.
    # When present, the agent loads prior turns for this (client_id, session_id)
    # and prepends a compact "conversation so far" block. Auto-injection is scoped
    # to the same session_id only — never across sessions or clients. Omitting it
    # (single-shot query) behaves exactly as before.
    session_id: str | None = None


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
    client: dict | None = None,
    session_id: str | None = None,
) -> tuple[str, list[dict], dict | None, str | None, dict | None]:
    """Run the gated verify pass + optional single corrective pass (B2 + C3).

    Returns (answer, citations, verification, caveat, corrected_meta).

    - verification is None when the gate decided the answer wasn't risky enough
      to verify.
    - When verification flags the answer, we surface a caveat and (if
      CORRECTIVE_PASS_ENABLED) run exactly ONE corrective regeneration — never a
      loop.
    - corrected_meta is None unless a corrective pass actually produced a new
      answer, in which case it carries the corrected generation's model_used,
      confidence and token/cache-token metrics so the caller can persist the
      real (Sonnet) metadata instead of the stale original values.
    """
    from taxflow.config import settings

    if not verify_mod.should_verify(confidence, citations, answer):
        return answer, citations, None, None, None

    model = verify_mod.verify_model_for(confidence, citations, answer)
    try:
        verification = await verifier.run(
            draft=answer, citations=citations, question=question, model=model
        )
    except Exception as e:  # noqa: BLE001 - verification must not break the response
        return answer, citations, {"overall_status": "parse_error", "issues": [], "error": str(e)}, None, None

    if not verify_mod.needs_correction(verification):
        return answer, citations, verification, None, None

    caveat = verify_mod.build_caveat(verification)

    # ONE bounded corrective pass (no loop): regenerate with the issues appended.
    if settings.CORRECTIVE_PASS_ENABLED:
        try:
            corrected = await agent.regenerate_with_feedback(
                question=question,
                client_id=client_id,
                issues=verification.get("issues", []),
                embedding=embedding,
                client=client,
                session_id=session_id,
            )
            verification["corrective_pass"] = True
            return corrected["answer"], corrected["citations"], verification, caveat, corrected
        except Exception:  # noqa: BLE001 - keep original answer if the retry fails
            verification["corrective_pass"] = False

    return answer, citations, verification, caveat, None


def _safe_to_cache(verification: dict | None) -> bool:
    """B3 cache-safety gate.

    Cache only when the answer was NOT risky (verification is None, so the gate
    skipped verification) or when verification explicitly and cleanly passed
    (overall_status == "verified"). Never cache a parse_error, verifier
    exception, needs_correction or unreliable result — otherwise a risky,
    unverified answer would be cached and future requests would skip
    verification entirely.
    """
    if verification is None:
        return True
    return verification.get("overall_status") == "verified"


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
    #
    # Task D3: skip the cache when a session_id is present — a session answer is
    # personalised with the "conversation so far" context, so it must not be
    # served from (or written to) the plain (client, question) cache key and risk
    # leaking one session's context into another.
    cached = (
        None
        if body.session_id
        else await answer_cache.get_cached_answer(client["id"], body.question)
    )
    if cached is not None:
        query_id = await asyncio.to_thread(
            _persist_cached_query, db, client, body.question, body.module, cached, start
        )
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
                    "session_id": body.session_id,
                }
            )
            .execute()
        )
        return row.data[0]["id"]

    embed_task = asyncio.create_task(embed(body.question))
    try:
        query_id = await asyncio.to_thread(_insert_query_row)
    except Exception:
        embed_task.cancel()
        raise

    try:
        embedding = await embed_task
        result = await agent.run(
            question=body.question,
            client_id=client["id"],
            embedding=embedding,
            client=client,
            session_id=body.session_id,
        )

        # Task B2/C3: gate the verify pass and feed its output back into the
        # stored answer (caveat + one bounded corrective pass).
        answer, citations, verification, caveat, corrected = await _maybe_verify(
            question=body.question,
            client_id=client["id"],
            answer=result["answer"],
            citations=result["citations"],
            confidence=result["confidence"],
            embedding=embedding,
            client=client,
            session_id=body.session_id,
        )
        stored_answer = f"{answer}\n\n{caveat}" if caveat else answer

        # When a corrective pass regenerated the answer, its metadata (Sonnet
        # model, confidence, token/cache-token counts) replaces the original
        # generation's — otherwise metrics/cost reporting would mislabel a
        # Sonnet-corrected answer as the first-pass model.
        meta = corrected or result

        update = {
            "status": "completed",
            "final_answer": stored_answer,
            "citations": citations,
            "confidence_score": meta["confidence"],
            "model_used": meta["model_used"],
            "input_tokens": meta["input_tokens"],
            "output_tokens": meta["output_tokens"],
            "cache_read_input_tokens": meta.get("cache_read_input_tokens"),
            "cache_creation_input_tokens": meta.get("cache_creation_input_tokens"),
            "wall_time_ms": int((time.time() - start) * 1000),
            "completed_at": "now()",
        }
        if verification is not None:
            update["verification_result"] = verification
        db.table("queries").update(update).eq("id", query_id).execute()

        await increment_usage(client["id"], "queries")

        # Task B3: cache the completed answer for this client only when it is
        # safe to (see _safe_to_cache — not risky, or cleanly verified). Never
        # cache a flagged/parse_error/unverified answer.
        # Task D3: never cache a session-personalised answer (see the cache-read
        # skip above) — its "conversation so far" context is session-specific.
        if not body.session_id and _safe_to_cache(verification):
            await answer_cache.store_answer(
                client["id"],
                body.question,
                {
                    "answer": stored_answer,
                    "citations": citations,
                    "confidence": meta["confidence"],
                    "model_used": meta["model_used"],
                },
            )

        return {
            "query_id": query_id,
            "answer": stored_answer,
            "citations": citations,
            "confidence": meta["confidence"],
            "model_used": meta["model_used"],
        }

    except Exception as e:
        db.table("queries").update({"status": "failed", "error_message": str(e)}).eq("id", query_id).execute()
        raise HTTPException(status_code=500, detail=f"Query failed: {e}") from e


def _persist_cached_query(
    db, client, question: str, module: str, cached: dict, start: float, extra: dict | None = None
) -> str:
    """Insert a completed queries row for a cache hit so history + metrics still
    reflect the served answer (marked model_used='cache')."""
    row = (
        db.table("queries")
        .insert(
            {
                "client_id": client["id"],
                "user_email": client["email"],
                "question": question,
                "module": module,
                "status": "completed",
                "final_answer": cached["answer"],
                "citations": cached["citations"],
                "confidence_score": cached["confidence"],
                "model_used": "cache",
                "wall_time_ms": int((time.time() - start) * 1000),
                "completed_at": "now()",
                **(extra or {}),
            }
        )
        .execute()
    )
    return row.data[0]["id"]


@router.get("/stream")
async def stream_query(
    question: str,
    client_ref: str | None = None,
    session_id: str | None = None,
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
    start = time.time()

    def _insert_query_row(status: str, extra: dict | None = None) -> str:
        row = (
            db.table("queries")
            .insert(
                {
                    "client_id": client["id"],
                    "user_email": client["email"],
                    "question": question,
                    "module": "research",
                    "status": status,
                    "client_ref": client_ref,
                    "session_id": session_id,
                    **(extra or {}),
                }
            )
            .execute()
        )
        return row.data[0]["id"]

    # Task B3: the dashboard streams every query, so the cost-saving cache must
    # be read on THIS path too (not just POST /query) — a hit skips OpenAI embed
    # + Anthropic generation entirely. Task D3: session-personalised queries
    # (session_id present) bypass the cache; their answer depends on prior turns.
    cached = (
        None
        if session_id
        else await answer_cache.get_cached_answer(client["id"], question)
    )
    if cached is not None:
        query_id = await asyncio.to_thread(
            _persist_cached_query,
            db,
            client,
            question,
            "research",
            cached,
            start,
            {"client_ref": client_ref},
        )
        await increment_usage(client["id"], "queries")

        async def cached_stream():
            yield f"data: {json.dumps({'type': 'token', 'text': cached['answer']})}\n\n"
            yield (
                "data: "
                + json.dumps(
                    {
                        "type": "final",
                        "citations": cached["citations"],
                        "query_id": query_id,
                        "model_used": "cache",
                        "confidence": cached["confidence"],
                        "cached": True,
                    }
                )
                + "\n\n"
            )
            yield f"data: {json.dumps({'type': 'verification', 'overall_status': 'not_verified', 'issues': []})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(cached_stream(), media_type="text/event-stream")

    # As in POST /query: auth + trial gate (Depends) have already passed before
    # this body runs, so the paid embed cannot fire for a 401/402 request. Overlap
    # the embed with the queries-row insert (Task A4) and reuse the single vector
    # for both global and firm retrieval inside run_stream(). Insert first, then
    # await the embed under the query_id so an embed failure marks the row failed
    # rather than leaving it stuck in "processing".
    embed_task = asyncio.create_task(embed(question))
    try:
        query_id = await asyncio.to_thread(_insert_query_row, "processing")
    except Exception:
        embed_task.cancel()
        raise
    try:
        embedding = await embed_task
    except Exception as e:
        db.table("queries").update({"status": "failed", "error_message": str(e)}).eq(
            "id", query_id
        ).execute()
        raise HTTPException(status_code=500, detail=f"Query failed: {e}") from e

    async def generate():
        answer_parts: list[str] = []
        citations: list[dict] = []
        final_meta: dict = {}

        async for event in agent.run_stream(
            question=question,
            client_id=client["id"],
            embedding=embedding,
            client=client,
            session_id=session_id,
        ):
            if event["type"] == "token":
                answer_parts.append(event["text"])
                yield f"data: {json.dumps(event)}\n\n"
            elif event["type"] == "final":
                citations = event["citations"]
                final_meta = event
                # Surface the routed model + confidence so the UI reflects the
                # actual model (Haiku or routed Sonnet) instead of hardcoding one.
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "type": "final",
                            "citations": citations,
                            "query_id": query_id,
                            "model_used": event.get("model_used"),
                            "confidence": event.get("confidence"),
                        }
                    )
                    + "\n\n"
                )

        final_answer = final_meta.get("answer") or "".join(answer_parts)
        confidence = final_meta.get("confidence", 0.0)

        # Task B2/C3: gate the verify pass in the stream path too, feeding its
        # output back (caveat + one bounded corrective pass) instead of running
        # Sonnet on every answer.
        answer, citations, verification, caveat, corrected = await _maybe_verify(
            question=question,
            client_id=client["id"],
            answer=final_answer,
            citations=citations,
            confidence=confidence,
            embedding=embedding,
            client=client,
            session_id=session_id,
        )
        stored_answer = f"{answer}\n\n{caveat}" if caveat else answer

        # If a corrective pass regenerated the answer, its metadata replaces the
        # streamed first-pass metadata so persisted metrics reflect the model
        # (Sonnet) and tokens that actually produced the stored answer.
        confidence = corrected["confidence"] if corrected else confidence
        model_used = corrected["model_used"] if corrected else final_meta.get("model_used")
        input_tokens = corrected["input_tokens"] if corrected else final_meta.get("input_tokens")
        output_tokens = corrected["output_tokens"] if corrected else final_meta.get("output_tokens")
        cache_read = (
            corrected["cache_read_input_tokens"]
            if corrected
            else final_meta.get("cache_read_input_tokens")
        )
        cache_creation = (
            corrected["cache_creation_input_tokens"]
            if corrected
            else final_meta.get("cache_creation_input_tokens")
        )

        # Task C5: persist model_used/confidence/tokens/wall_time on the stream
        # path (previously only POST /query stored these), plus the B1 cache
        # tokens on both paths.
        update = {
            "status": "completed",
            "final_answer": stored_answer,
            "citations": citations,
            "confidence_score": confidence,
            "model_used": model_used,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": cache_creation,
            "wall_time_ms": int((time.time() - start) * 1000),
            "completed_at": "now()",
        }
        if verification is not None:
            update["verification_result"] = verification
        db.table("queries").update(update).eq("id", query_id).execute()
        await increment_usage(client["id"], "queries")

        # Task B3: cache the streamed answer only when it is safe to (see
        # _safe_to_cache). Task D3: never cache a session-personalised answer.
        if not session_id and _safe_to_cache(verification):
            await answer_cache.store_answer(
                client["id"],
                question,
                {
                    "answer": stored_answer,
                    "citations": citations,
                    "confidence": confidence,
                    "model_used": model_used,
                },
            )

        # The `final`/token events above already streamed the FIRST-pass answer.
        # If verification produced a caveat or a corrective pass replaced the
        # answer, emit a `correction` event carrying the authoritative stored
        # answer + citations + caveat so the UI can replace what it displayed
        # (the streamed tokens can otherwise differ from queries.final_answer).
        if caveat or corrected:
            yield (
                "data: "
                + json.dumps(
                    {
                        "type": "correction",
                        "answer": stored_answer,
                        "citations": citations,
                        "caveat": caveat,
                        "model_used": model_used,
                        "confidence": confidence,
                    }
                )
                + "\n\n"
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
