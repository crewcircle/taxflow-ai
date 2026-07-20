import asyncio

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from taxflow.config import settings
from taxflow.db import get_db
from taxflow.middleware.auth import get_current_client
from taxflow.providers import get_document_renderer
from taxflow.services.agents.document_graph import document_graph
from taxflow.services.knowledge.embedder import embed

router = APIRouter(prefix="/documents", tags=["documents"])

TEMPLATE_REGISTRY = {
    "advice_memo": "Tax advice memo",
    "client_letter": "Client letter",
    "ato_response": "ATO correspondence response",
    "remission_request": "Penalty remission request",
    "objection_letter": "Formal objection letter",
    "private_ruling_application": "Private binding ruling application",
    "engagement_letter": "Client engagement letter",
    "payg_variation": "PAYG withholding variation request",
    "fbt_declaration": "FBT declaration",
}

# Task C4: the approved client-facing document types whose content is embedded
# on save into engagement_context (per the plan's Decisions section — there is
# no client_letter type in the engagement-context set).
ENGAGEMENT_CONTEXT_TYPES = {
    "advice_memo",
    "objection_letter",
    "ato_response",
    "engagement_letter",
}


class GenerateDocumentRequest(BaseModel):
    query_id: str | None = None
    document_type: str
    title: str
    content_md: str
    client_ref: str | None = None


class ApproveDocumentRequest(BaseModel):
    approved_by: str


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

    if body.client_ref:
        try:
            await asyncio.to_thread(db.firm_clients.upsert, client["id"], body.client_ref)
        except Exception:  # noqa: BLE001 - never block saving the document
            pass

    # Chat answers are the raw research answer, not a formal memo/letter - only
    # reformat here, on demand, when actually saving one as a specific document
    # type (document_graph.py routes advice_memo/client_letter through their
    # own reformatting node; every other type passes content_md through
    # unchanged, same as before this graph existed).
    original_question = None
    citations: list[dict] = []
    if body.query_id:
        query = await asyncio.to_thread(
            db.queries.get_question_citations, client["id"], body.query_id
        )
        if query:
            original_question = query["question"]
            citations = query["citations"] or []

    final_state = await document_graph.ainvoke(
        {
            "document_type": body.document_type,
            "content_md": body.content_md,
            "original_question": original_question,
            "citations": citations,
            "client_id": client["id"],
        }
    )
    content_md = final_state["result_md"]

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

    # Task C4: approved client-facing document types are embedded on save into
    # the engagement_context store so future research queries scoped to the SAME
    # client_ref can retrieve prior memos as advisory context. Wrapped in a broad
    # try/except (like the firm_clients.upsert above) so an embed/insert failure
    # never blocks the document save — the document row is already persisted.
    if body.document_type in ENGAGEMENT_CONTEXT_TYPES and settings.ENGAGEMENT_CONTEXT_ENABLED:
        try:
            embedding = await embed(content_md)
            await asyncio.to_thread(
                db.engagement_context.insert,
                {
                    "client_id": client["id"],
                    "client_ref": body.client_ref,
                    "document_id": result["id"],
                    "document_type": body.document_type,
                    "title": body.title,
                    "content": content_md,
                    "embedding": embedding,
                },
            )
        except Exception:  # noqa: BLE001 - never block saving the document
            pass

    # Task C5: saving an advice_memo also creates a PENDING knowledge_suggestion
    # (approval-gated learning loop). This is additive to the C4 engagement
    # context insert above: the auto-embedded memo stays out of the authoritative
    # firm_knowledge store until a partner explicitly approves the suggestion.
    # Best-effort — a suggestion failure never blocks the already-saved document.
    if body.document_type == "advice_memo" and settings.LEARNING_LOOP_ENABLED:
        try:
            await asyncio.to_thread(
                db.knowledge_suggestions.insert,
                {
                    "client_id": client["id"],
                    "source_document_id": result["id"],
                    "title": body.title,
                    "content": content_md,
                    "reason": "saved_memo",
                },
            )
        except Exception:  # noqa: BLE001 - never block saving the document
            pass

    return result


@router.patch("/{document_id}/approve")
async def approve_document(
    document_id: str,
    body: ApproveDocumentRequest,
    client=Depends(get_current_client),
    db=Depends(get_db),
):
    """Good-faith sign-off, not a security control - `approved_by` is a name the
    caller picked from the firm's own staff_directory (Settings), not tied to a
    per-person login (the product has no multi-user auth to hang that off yet).
    """
    doc = await asyncio.to_thread(db.documents.get_for_client, client["id"], document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    await asyncio.to_thread(
        db.documents.update_status,
        client["id"],
        document_id,
        "approved",
        {"approved_by": body.approved_by, "approved_at": "now()"},
    )
    return await asyncio.to_thread(db.documents.get_for_client, client["id"], document_id)


@router.get("/{document_id}")
async def get_document(
    document_id: str,
    client=Depends(get_current_client),
    db=Depends(get_db),
):
    """Return a document's ``content_md`` + metadata for the in-app viewer.

    Client_id-scoped (404 for a foreign doc); the download route stays for the
    docx/pdf exports. ``get_for_client`` already ``SELECT *`` so content_md is
    included with no repo change.
    """
    doc = await asyncio.to_thread(db.documents.get_for_client, client["id"], document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


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
