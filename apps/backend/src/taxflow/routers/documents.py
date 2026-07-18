import asyncio

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from taxflow.db import get_db
from taxflow.middleware.auth import get_current_client
from taxflow.providers import get_document_renderer
from taxflow.services.agents.draft import DraftAgent

router = APIRouter(prefix="/documents", tags=["documents"])
drafter = DraftAgent()

TEMPLATE_REGISTRY = {
    "advice_memo": "Tax advice memo",
    "ato_response": "ATO correspondence response",
    "remission_request": "Penalty remission request",
    "objection_letter": "Formal objection letter",
    "private_ruling_application": "Private binding ruling application",
    "engagement_letter": "Client engagement letter",
    "payg_variation": "PAYG withholding variation request",
    "fbt_declaration": "FBT declaration",
}


class GenerateDocumentRequest(BaseModel):
    query_id: str | None = None
    document_type: str
    title: str
    content_md: str
    client_ref: str | None = None


@router.get("/templates")
async def list_templates():
    return [{"type": k, "label": v} for k, v in TEMPLATE_REGISTRY.items()]


@router.get("")
async def list_documents(client=Depends(get_current_client), db=Depends(get_db)):
    return await asyncio.to_thread(db.documents.list_for_client, client["id"])


@router.post("/generate")
async def generate_document(
    body: GenerateDocumentRequest, client=Depends(get_current_client), db=Depends(get_db)
):
    if body.document_type not in TEMPLATE_REGISTRY:
        raise HTTPException(status_code=400, detail=f"Unknown document_type: {body.document_type}")

    content_md = body.content_md
    # Chat answers are the raw research answer, not a formal memo - only
    # reformat into the firm's 5-section structure here, on demand, when
    # actually saving one as an advice memo document.
    if body.document_type == "advice_memo" and body.query_id:
        query = await asyncio.to_thread(
            db.queries.get_question_citations, client["id"], body.query_id
        )
        if query:
            try:
                draft_result = await drafter.run(
                    research_result={"answer": body.content_md, "citations": query["citations"] or []},
                    original_question=query["question"],
                    client_id=client["id"],
                )
                content_md = draft_result["draft"]
            except Exception:  # noqa: BLE001 - drafting failure must not block saving the document
                pass

    result = await asyncio.to_thread(
        db.documents.insert,
        {
            "client_id": client["id"],
            "query_id": body.query_id,
            "document_type": body.document_type,
            "title": body.title,
            "content_md": content_md,
            "client_ref": body.client_ref,
        },
    )
    return result


@router.get("/{document_id}/download")
async def download_document(document_id: str, fmt: str = "docx", client=Depends(get_current_client), db=Depends(get_db)):
    doc = await asyncio.to_thread(db.documents.get_for_client, client["id"], document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    renderer = get_document_renderer()
    render_doc = {
        "content_md": doc["content_md"],
        "title": doc["title"],
        "client_name": client["business_name"],
        "date": doc["created_at"],
    }
    if fmt == "pdf":
        content = renderer.render_pdf(render_doc)
        media_type = "application/pdf"
    else:
        content = renderer.render_docx(render_doc)
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    return Response(content=content, media_type=media_type)
