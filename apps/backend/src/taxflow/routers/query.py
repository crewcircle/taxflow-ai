"""
Query router. Handles research queries through the full agent pipeline.
All endpoints require valid Supabase JWT (enforced by auth middleware).
"""
import json
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from taxflow.db import get_db
from taxflow.middleware.auth import get_current_client
from taxflow.middleware.trial_gate import check_trial_gate, increment_usage
from taxflow.services.agents.research import ResearchAgent

router = APIRouter(prefix="/query", tags=["query"])
agent = ResearchAgent()


class QueryRequest(BaseModel):
    question: str
    module: str = "research"


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


@router.get("/{query_id}")
async def get_query(query_id: str, client=Depends(get_current_client), db=Depends(get_db)):
    result = db.table("queries").select("*").eq("id", query_id).eq("client_id", client["id"]).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Query not found")
    return result.data[0]


@router.get("/stream/{query_id}")
async def stream_query(query_id: str, question: str, client=Depends(get_current_client)):
    """Server-Sent Events stream of Research Agent output."""

    async def generate():
        async for token in agent.run_stream(question=question, client_id=client["id"]):
            yield f"data: {json.dumps({'token': token})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
