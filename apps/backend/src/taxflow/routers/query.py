"""
Query router. Handles research queries through the full agent pipeline.
All endpoints require valid Supabase JWT (enforced by auth middleware).
"""
import json
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from taxflow.db import get_db, get_supabase_client
from taxflow.middleware.auth import get_current_client
from taxflow.middleware.trial_gate import check_trial_gate, increment_usage
from taxflow.services.agents.draft import DraftAgent
from taxflow.services.agents.research import ResearchAgent
from taxflow.services.agents.verify import VerifyAgent

router = APIRouter(prefix="/query", tags=["query"])
agent = ResearchAgent()
drafter = DraftAgent()
verifier = VerifyAgent()


class QueryRequest(BaseModel):
    question: str
    module: str = "research"


@router.get("")
async def list_queries(client=Depends(get_current_client), db=Depends(get_db)):
    """Recent query history for the sidebar - newest first."""
    result = (
        db.table("queries")
        .select("id, question, status, model_used, confidence_score, verification_result, client_ref, created_at")
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

    query_row = (
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
    query_id = query_row.data[0]["id"]

    try:
        result = await agent.run(question=body.question, client_id=client["id"])

        db.table("queries").update(
            {
                "status": "completed",
                "final_answer": result["answer"],
                "citations": result["citations"],
                "confidence_score": result["confidence"],
                "model_used": result["model_used"],
                "input_tokens": result["input_tokens"],
                "output_tokens": result["output_tokens"],
                "wall_time_ms": int((time.time() - start) * 1000),
                "completed_at": "now()",
            }
        ).eq("id", query_id).execute()

        await increment_usage(client["id"], "queries")

        return {
            "query_id": query_id,
            "answer": result["answer"],
            "citations": result["citations"],
            "confidence": result["confidence"],
            "model_used": result["model_used"],
        }

    except Exception as e:
        db.table("queries").update({"status": "failed", "error_message": str(e)}).eq("id", query_id).execute()
        raise HTTPException(status_code=500, detail=f"Query failed: {e}") from e


@router.get("/stream")
async def stream_query(
    question: str,
    client_ref: str | None = None,
    client=Depends(get_current_client),
    _trial=Depends(check_trial_gate),
):
    """Server-Sent Events stream of the research -> draft -> verify pipeline.

    Emits: {"type": "token", ...} while the raw research answer streams, then
    {"type": "final", "citations": [...]}, then - once the Draft Agent has
    rewritten the raw answer into the firm's 5-section advice memo - a
    {"type": "draft", "text": ...} event, then an async
    {"type": "verification", "status": ..., "issues": [...]} event checked
    against the draft (what actually ships), not the raw research text.
    Streaming keeps the first-token latency low; draft + verification land a
    few seconds later without blocking the initial response.
    """
    db = get_supabase_client()
    query_row = (
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
    query_id = query_row.data[0]["id"]

    async def generate():
        answer_parts: list[str] = []
        citations: list[dict] = []

        async for event in agent.run_stream(question=question, client_id=client["id"]):
            if event["type"] == "token":
                answer_parts.append(event["text"])
            elif event["type"] == "final":
                citations = event["citations"]
            yield f"data: {json.dumps(event)}\n\n"

        raw_answer = "".join(answer_parts)

        try:
            draft_result = await drafter.run(
                research_result={"answer": raw_answer, "citations": citations},
                original_question=question,
                client_id=client["id"],
            )
            final_answer = draft_result["draft"]
        except Exception:  # noqa: BLE001 - drafting failure must not break the response
            final_answer = raw_answer

        yield f"data: {json.dumps({'type': 'draft', 'text': final_answer})}\n\n"

        db.table("queries").update(
            {
                "status": "completed",
                "final_answer": final_answer,
                "citations": citations,
                "completed_at": "now()",
            }
        ).eq("id", query_id).execute()
        await increment_usage(client["id"], "queries")

        try:
            verification = await verifier.run(draft=final_answer, citations=citations, question=question)
        except Exception as e:  # noqa: BLE001 - verification failure must not break the response
            verification = {"overall_status": "parse_error", "issues": [], "error": str(e)}

        db.table("queries").update({"verification_result": verification}).eq("id", query_id).execute()

        yield f"data: {json.dumps({'type': 'verification', **verification})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# Must stay below /stream - FastAPI matches routes in declaration order, and this
# wildcard path param would otherwise swallow /query/stream as query_id="stream".
@router.get("/{query_id}")
async def get_query(query_id: str, client=Depends(get_current_client), db=Depends(get_db)):
    result = db.table("queries").select("*").eq("id", query_id).eq("client_id", client["id"]).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Query not found")
    return result.data[0]
