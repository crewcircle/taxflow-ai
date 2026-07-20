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

from taxflow.config import settings
from taxflow.db import get_db
from taxflow.middleware.auth import get_current_client
from taxflow.middleware.trial_gate import check_trial_gate, increment_usage
from taxflow.services import answer_cache
from taxflow.services.agents.graph import research_graph
from taxflow.services.eval.citations import check_citation_validity
from taxflow.services.eval.cost import run_cost
from taxflow.services.knowledge.embedder import embed

router = APIRouter(prefix="/query", tags=["query"])
# The compiled research graph (Task A6) owns generation + the gated verify /
# at-most-once corrective pass; both endpoints drive it directly.


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
    # Task C4: an optional client-engagement reference. When present, prior
    # engagement memos saved for this same client_ref are retrieved as advisory
    # context (already a query param on GET /stream; added here for POST parity).
    client_ref: str | None = None


class FeedbackRequest(BaseModel):
    rating: str  # "up" | "down"
    note: str | None = None


def _build_final_trace(
    trace: dict | None,
    verification: dict | None,
    corrected: dict | None,
    *,
    re_retrieved: bool = False,
    re_reason: str | None = None,
    re_detail: str | None = None,
    first_pass: dict | None = None,
) -> dict:
    """Combine the agent's retrieval/generation trace with the verify (+ optional
    corrective regeneration) stage into the single record persisted on the
    queries row and shown in the "why this answer?" UI. `trace` is None for a
    cache hit (no pipeline actually ran).

    The top-level ``retrieval``/``generation`` blocks always describe the FINAL
    stored answer (the corrected/widened one when a corrective pass ran). When a
    corrective pass ran, ``trace.passes`` carries the first-pass-vs-corrected
    diff — ``first_pass`` comes from the ``AgentState["first_pass"]`` snapshot
    (works for BOTH POST and SSE, since the corrective pass overwrites
    ``final["confidence"]``) and ``corrected`` from the corrected pass's trace.
    ``trace.re_retrieval`` is emitted only when a re-retrieval actually fired."""
    if trace is None:
        return {"retrieval": None, "generation": {"model": "cache"}, "verification": None}
    # Shallow-copy the agent trace so additive top-level blocks the agent builds
    # (``firm``/``session`` — firm profile/voice/items/usage_trend, prior turns,
    # engagement memos, client_ref — and any future block) survive into the
    # persisted/returned trace. ``retrieval``/``generation`` come straight from
    # ``trace`` so they still describe the FINAL stored answer.
    result = dict(trace)
    if verification is None:
        result["verification"] = {"ran": False}
    else:
        result["verification"] = {
            "ran": True,
            "status": verification.get("overall_status"),
            "issue_count": len(verification.get("issues", [])),
            "corrective_pass": verification.get("corrective_pass", False),
        }
    if corrected is not None:
        result["corrective_generation"] = corrected["trace"]["generation"]
        # The stored answer is the corrected one, so the top-level blocks already
        # describe it; trace.passes records the first-pass-vs-corrected diff. The
        # first-pass meta comes from the state snapshot (POST must not read
        # final["confidence"], which the corrective pass overwrote).
        first = first_pass or {}
        corrected_gen = corrected["trace"]["generation"]
        result["passes"] = {
            "first_pass": {
                "model": first.get("model"),
                "confidence": first.get("confidence"),
            },
            "corrected": {
                "model": corrected_gen.get("model"),
                "confidence": corrected_gen.get("confidence"),
            },
            "changed": True,
        }
    # Re-retrieval block: omitted entirely unless a re-retrieval fired.
    if re_retrieved:
        result["re_retrieval"] = {
            "fired": True,
            "reason": re_reason or "weak_signal",
            "detail": re_detail,
        }
    return result


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


def _observability_fields(answer: str, citations: list, trace: dict, meta: dict) -> dict:
    """Task 1b: per-query citation-validity + dollar cost for a live generation.

    Returns the additive observability columns (migration 035) for a
    non-cache-hit answer: ``citation_valid`` / ``invalid_citations`` from the
    deterministic citation checker and ``cost_usd`` from ``run_cost`` over the
    generation's tier + token counters. ``model_used`` here is the abstract tier
    ("haiku"/"sonnet") priced against ``EVAL_MODEL_PRICING``; None token counters
    are coerced to 0 so a partial usage record never blows up.
    """
    validity = check_citation_validity(
        {"answer": answer, "citations": citations, "trace": trace}
    )
    invalid = {
        "fabricated_markers": validity["fabricated_markers"],
        "unmatched_citations": validity["unmatched_citations"],
    }
    cost = run_cost(
        meta["model_used"],
        meta.get("input_tokens") or 0,
        meta.get("output_tokens") or 0,
        cache_read=meta.get("cache_read_input_tokens") or 0,
        cache_creation=meta.get("cache_creation_input_tokens") or 0,
    )
    return {
        "citation_valid": validity["valid"],
        # validity["valid"] is precisely "no fabricated and no unmatched", so
        # store the detail only when the answer is invalid (else NULL).
        "invalid_citations": None if validity["valid"] else invalid,
        "cost_usd": cost,
    }


@router.get("")
async def list_queries(client=Depends(get_current_client), db=Depends(get_db)):
    """Recent query history for the sidebar - newest first."""
    return await asyncio.to_thread(db.queries.list_recent, client["id"], 50)


class SessionLabelRequest(BaseModel):
    label: str


@router.get("/sessions")
async def list_sessions(client=Depends(get_current_client), db=Depends(get_db)):
    """Labels for this client's named conversation threads - unlabelled
    sessions simply aren't in this list, the sidebar falls back to the first
    question's text for those."""
    return await asyncio.to_thread(db.query_sessions.list_for_client, client["id"])


@router.patch("/sessions/{session_id}")
async def rename_session(
    session_id: str,
    body: SessionLabelRequest,
    client=Depends(get_current_client),
    db=Depends(get_db),
):
    label = body.label.strip()
    if not label:
        raise HTTPException(status_code=400, detail="Label cannot be empty")
    return await asyncio.to_thread(db.query_sessions.upsert_label, client["id"], session_id, label)


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
        # A cache hit means this exact question already has a completed row,
        # so count first and persist the new row after (mirrors the
        # count-before-completed ordering used on the non-cached path).
        repeat_count = await answer_cache.count_prior_asks(client["id"], body.question)
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
            "repeat_count": repeat_count,
            "trace": _build_final_trace(None, None, None),
        }

    # Auth (get_current_client) and the trial gate (check_trial_gate) run as
    # Depends and MUST fully pass before this body executes, so the paid OpenAI
    # embed below can never fire for an invalid-token (401) or expired/capped
    # trial (402) request. Once past the gate, overlap the embed with the
    # queries-row insert (Task A4): both are independent I/O, so gather them and
    # await the embedding just before it is threaded into the graph's retrieval.
    def _insert_query_row() -> str:
        row = db.queries.insert(
            {
                "client_id": client["id"],
                "user_email": client["email"],
                "question": body.question,
                "module": body.module,
                "status": "processing",
                "session_id": body.session_id,
                "client_ref": body.client_ref,
            }
        )
        return row["id"]

    embed_task = asyncio.create_task(embed(body.question))
    try:
        query_id = await asyncio.to_thread(_insert_query_row)
    except Exception:
        embed_task.cancel()
        raise

    try:
        embedding = await embed_task

        # Task A6: drive the compiled research graph, which internalises
        # generation, the gated verify pass and the at-most-once corrective pass.
        # The final state carries the (possibly corrected) answer plus the
        # metadata the router persists — no separate agent.run/_maybe_verify.
        initial_state = {
            "question": body.question,
            "client": client,
            "client_id": client["id"],
            "session_id": body.session_id,
            "client_ref": body.client_ref,
            "embedding": embedding,
            "streaming": False,
            "corrective_count": 0,
            "re_retrieved": False,
        }
        final = await research_graph.ainvoke(initial_state)

        answer = final["answer"]
        citations = final["citations"]
        verification = final.get("verification")
        caveat = final.get("caveat")
        corrected_meta = final.get("corrected_meta")
        stored_answer = f"{answer}\n\n{caveat}" if caveat else answer

        # Firm Knowledge suggestion trigger: how many times has this client
        # already asked essentially this question? Counted before the update
        # below marks this row 'completed', so it never counts itself.
        repeat_count = await answer_cache.count_prior_asks(client["id"], body.question)

        # When a corrective pass regenerated the answer, its metadata (Sonnet
        # model, confidence, token/cache-token counts) replaces the original
        # generation's — otherwise metrics/cost reporting would mislabel a
        # Sonnet-corrected answer as the first-pass model. Absent a corrective
        # pass, read the first-pass metrics straight off the final state.
        meta = corrected_meta or {
            "confidence": final["confidence"],
            "model_used": final["routed_tier"],
            "model_id": final.get("model_id"),
            "input_tokens": final.get("input_tokens"),
            "output_tokens": final.get("output_tokens"),
            "cache_read_input_tokens": final.get("cache_read_input_tokens"),
            "cache_creation_input_tokens": final.get("cache_creation_input_tokens"),
        }
        trace = _build_final_trace(
            final.get("trace"),
            verification,
            corrected_meta,
            re_retrieved=final.get("re_retrieved", False),
            re_reason=final.get("re_reason"),
            re_detail=final.get("re_detail"),
            first_pass=final.get("first_pass"),
        )

        update = {
            "status": "completed",
            "final_answer": stored_answer,
            "citations": citations,
            "confidence_score": meta["confidence"],
            "model_used": meta["model_used"],
            "model_id": meta.get("model_id"),
            "input_tokens": meta["input_tokens"],
            "output_tokens": meta["output_tokens"],
            "cache_read_input_tokens": meta.get("cache_read_input_tokens"),
            "cache_creation_input_tokens": meta.get("cache_creation_input_tokens"),
            "wall_time_ms": int((time.time() - start) * 1000),
            "completed_at": "now()",
            "trace": trace,
            # Task 1b: live citation-validity + dollar cost of this generation.
            **_observability_fields(stored_answer, citations, trace, meta),
        }
        if verification is not None:
            update["verification_result"] = verification
        await asyncio.to_thread(db.queries.update, client["id"], query_id, update)

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
            "repeat_count": repeat_count,
            "trace": trace,
        }

    except Exception as e:
        await asyncio.to_thread(
            db.queries.update, client["id"], query_id, {"status": "failed", "error_message": str(e)}
        )
        raise HTTPException(status_code=500, detail=f"Query failed: {e}") from e


def _persist_cached_query(
    db, client, question: str, module: str, cached: dict, start: float, extra: dict | None = None
) -> str:
    """Insert a completed queries row for a cache hit so history + metrics still
    reflect the served answer (marked model_used='cache').

    Task 1b/1c: a cache hit ran no pipeline (no tokens, no trace.retrieval, and
    model_used='cache' is not a priced tier), so we do NOT call run_cost /
    check_citation_validity. We store ``cost_usd = 0`` (a served-from-cache
    answer genuinely cost nothing) and leave ``citation_valid`` /
    ``invalid_citations`` / ``model_id`` NULL — validity/model attribution is
    "not measured" for a cache hit.
    """
    row = db.queries.insert(
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
            "cost_usd": 0,
            "wall_time_ms": int((time.time() - start) * 1000),
            "completed_at": "now()",
            "trace": _build_final_trace(None, None, None),
            **(extra or {}),
        }
    )
    return row["id"]


@router.get("/stream")
async def stream_query(
    question: str,
    client_ref: str | None = None,
    session_id: str | None = None,
    client=Depends(get_current_client),
    _trial=Depends(check_trial_gate),
    db=Depends(get_db),
):
    """Server-Sent Events stream of the research -> verify pipeline.

    Emits: {"type": "token", ...} while the answer streams, then
    {"type": "final", "citations": [...], "query_id": ...} - this raw research
    answer is what's shown and stored as-is, not rewritten into a formal memo
    (that reformatting only happens on demand when saving as an advice_memo
    document). Then an async {"type": "verification", "status": ...,
    "issues": [...]} event checked against this same answer.
    """
    start = time.time()

    # Client register (Settings audit follow-up): grows organically from real
    # use rather than requiring firms to pre-seed a client list. Upsert is a
    # no-op on repeat names (ON CONFLICT DO NOTHING) and must never block the
    # question being answered.
    if client_ref:
        try:
            await asyncio.to_thread(db.firm_clients.upsert, client["id"], client_ref)
        except Exception:  # noqa: BLE001
            pass

    def _insert_query_row(status: str, extra: dict | None = None) -> str:
        row = db.queries.insert(
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
        return row["id"]

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
        # A cache hit means this exact question already has a completed row, so
        # count prior asks BEFORE persisting the new cached row (mirrors the
        # count-before-completed ordering on the non-cached path) so it never
        # counts itself.
        repeat_count = await answer_cache.count_prior_asks(client["id"], question)
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
            yield f"data: {json.dumps({'type': 'trace', **_build_final_trace(None, None, None)})}\n\n"
            yield f"data: {json.dumps({'type': 'repeat_count', 'count': repeat_count})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(cached_stream(), media_type="text/event-stream")

    # As in POST /query: auth + trial gate (Depends) have already passed before
    # this body runs, so the paid embed cannot fire for a 401/402 request. Overlap
    # the embed with the queries-row insert (Task A4) and reuse the single vector
    # for both global and firm retrieval inside the graph. Insert first, then
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
        await asyncio.to_thread(
            db.queries.update, client["id"], query_id, {"status": "failed", "error_message": str(e)}
        )
        raise HTTPException(status_code=500, detail=f"Query failed: {e}") from e

    async def generate():
        latest_values: dict = {}
        first_pass_snapshot: dict = {}

        # Task A6: drive the compiled research graph in multi-mode streaming.
        # ``stream_mode=["custom","values"]`` makes LangGraph (>=1.2,<2) yield
        # (mode, chunk) TUPLES: "custom" carries the generate node's {"token": ...}
        # writer events, "values" carries a full state snapshot on EVERY update.
        # We forward tokens as they arrive, keep the LATEST values snapshot (the
        # post-graph final state) for persistence + the `correction` event, and
        # separately capture the FIRST snapshot with a populated `answer` — the
        # one right after the generate node, BEFORE verify/corrective can
        # overwrite answer/citations/confidence in state — for the `final` event,
        # so `final` always reflects the first-pass streamed answer.
        initial_state = {
            "question": question,
            "client": client,
            "client_id": client["id"],
            "session_id": session_id,
            "client_ref": client_ref,
            "embedding": embedding,
            "streaming": True,
            "corrective_count": 0,
            "re_retrieved": False,
        }
        async for mode, chunk in research_graph.astream(
            initial_state, stream_mode=["custom", "values"]
        ):
            if mode == "custom":
                text = chunk["token"]
                yield f"data: {json.dumps({'type': 'token', 'text': text})}\n\n"
            elif mode == "values":
                latest_values = chunk
                if not first_pass_snapshot and chunk.get("answer"):
                    first_pass_snapshot = chunk

        final = latest_values

        # The `final` event carries the FIRST-pass citations/model/confidence
        # captured right after the generate node; the streamed tokens above
        # already delivered the answer text. Emitted ONCE after the loop — never
        # on an interim `values` snapshot. (Fall back to the final snapshot only
        # if no first-pass snapshot was captured, e.g. an empty answer.)
        first_pass = first_pass_snapshot or final
        first_pass_citations = first_pass.get("citations", [])
        first_pass_model = first_pass.get("routed_tier")
        first_pass_confidence = first_pass.get("confidence", 0.0)

        answer = final["answer"]
        citations = final.get("citations", [])
        verification = final.get("verification")
        caveat = final.get("caveat")
        corrected_meta = final.get("corrected_meta")

        yield (
            "data: "
            + json.dumps(
                {
                    "type": "final",
                    "citations": first_pass_citations,
                    "query_id": query_id,
                    "model_used": first_pass_model,
                    "confidence": first_pass_confidence,
                }
            )
            + "\n\n"
        )

        stored_answer = f"{answer}\n\n{caveat}" if caveat else answer

        # If a corrective pass regenerated the answer, its metadata replaces the
        # streamed first-pass metadata so persisted metrics reflect the model
        # (Sonnet) and tokens that actually produced the stored answer.
        if corrected_meta:
            confidence = corrected_meta["confidence"]
            model_used = corrected_meta["model_used"]
            model_id = corrected_meta.get("model_id")
            input_tokens = corrected_meta["input_tokens"]
            output_tokens = corrected_meta["output_tokens"]
            cache_read = corrected_meta.get("cache_read_input_tokens")
            cache_creation = corrected_meta.get("cache_creation_input_tokens")
        else:
            confidence = first_pass_confidence
            model_used = first_pass_model
            model_id = final.get("model_id")
            input_tokens = final.get("input_tokens")
            output_tokens = final.get("output_tokens")
            cache_read = final.get("cache_read_input_tokens")
            cache_creation = final.get("cache_creation_input_tokens")

        # Firm Knowledge suggestion trigger: count before the update below
        # marks this row 'completed', so it never counts itself.
        repeat_count = await answer_cache.count_prior_asks(client["id"], question)

        trace = _build_final_trace(
            final.get("trace"),
            verification,
            corrected_meta,
            re_retrieved=final.get("re_retrieved", False),
            re_reason=final.get("re_reason"),
            re_detail=final.get("re_detail"),
            first_pass=final.get("first_pass"),
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
            "model_id": model_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": cache_creation,
            "wall_time_ms": int((time.time() - start) * 1000),
            "completed_at": "now()",
            "trace": trace,
            # Task 1b: live citation-validity + dollar cost of this generation.
            **_observability_fields(
                stored_answer,
                citations,
                trace,
                {
                    "model_used": model_used,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cache_read_input_tokens": cache_read,
                    "cache_creation_input_tokens": cache_creation,
                },
            ),
        }
        if verification is not None:
            update["verification_result"] = verification
        await asyncio.to_thread(db.queries.update, client["id"], query_id, update)
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
        if caveat or corrected_meta:
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
        yield f"data: {json.dumps({'type': 'trace', **trace})}\n\n"
        yield f"data: {json.dumps({'type': 'repeat_count', 'count': repeat_count})}\n\n"

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

    owned = await asyncio.to_thread(db.queries.get_for_client, client["id"], query_id)
    if not owned:
        raise HTTPException(status_code=404, detail="Query not found")

    row = await asyncio.to_thread(
        db.query_feedback.insert,
        {
            "query_id": query_id,
            "client_id": client["id"],
            "rating": body.rating,
            "note": body.note,
        },
    )
    feedback_id = row["id"]

    # Task C2: a thumbs-DOWN WITH a note enqueues an async re-research job so the
    # background worker can re-run the answer with the user's stated issue and a
    # widened retrieval pool. Reviewer/verify flags stay synchronous (the inline
    # corrective pass) and are never enqueued here. The enqueue is at-most-once
    # per feedback row (UNIQUE(feedback_id) + ON CONFLICT DO NOTHING) — a dup
    # feedback returns None and does NOT re-enqueue or re-flag the query.
    re_research_enqueued = False
    note = (body.note or "").strip()
    if body.rating == "down" and note and settings.RE_RESEARCH_ENABLED:
        job = await asyncio.to_thread(
            db.re_research_jobs.enqueue,
            {
                "client_id": client["id"],
                "query_id": query_id,
                "feedback_id": feedback_id,
                "feedback_note": note,
                "original_answer": owned.get("final_answer"),
            },
        )
        if job is not None:
            re_research_enqueued = True
            await asyncio.to_thread(
                db.queries.set_re_research_status, client["id"], query_id, "pending"
            )

    # Task C5: a thumbs-UP creates a PENDING knowledge_suggestion from the
    # question + answer (approval-gated learning loop — a partner later approves
    # it into firm_knowledge). De-duped per query via exists_for_query so a
    # second thumbs-up on the same query never creates a second pending
    # suggestion. Best-effort: a suggestion failure never fails the feedback.
    if body.rating == "up" and settings.LEARNING_LOOP_ENABLED:
        already = await asyncio.to_thread(
            db.knowledge_suggestions.exists_for_query, client["id"], query_id
        )
        if not already:
            title = (owned.get("question") or "").strip()[:80] or "Suggested note"
            content = (owned.get("final_answer") or "").strip()
            if content:
                await asyncio.to_thread(
                    db.knowledge_suggestions.insert,
                    {
                        "client_id": client["id"],
                        "source_query_id": query_id,
                        "title": title,
                        "content": content,
                        "reason": "thumbs_up",
                    },
                )

    return {
        "id": feedback_id,
        "query_id": query_id,
        "rating": body.rating,
        "re_research_enqueued": re_research_enqueued,
    }


# Must stay below /stream - FastAPI matches routes in declaration order, and this
# wildcard path param would otherwise swallow /query/stream as query_id="stream".
@router.get("/{query_id}")
async def get_query(query_id: str, client=Depends(get_current_client), db=Depends(get_db)):
    result = await asyncio.to_thread(db.queries.get_for_client, client["id"], query_id)
    if not result:
        raise HTTPException(status_code=404, detail="Query not found")
    return result
