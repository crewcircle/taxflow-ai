import asyncio

import pdfplumber
import psycopg2
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from pydantic import BaseModel

from taxflow.db import get_db
from taxflow.middleware.auth import get_current_client, require_permission
from taxflow.rbac import has_permission
from taxflow.routers._shared import ensure_engagement_owned, register_firm_client
from taxflow.services.ato_correspondence.classifier import ATOLetterClassifier
from taxflow.services.ato_correspondence.drafter import ATOResponseDrafter
from taxflow.services.ato_correspondence.handlers import get_handler
from taxflow.services.agents.research import build_client_profile

router = APIRouter(prefix="/ato-response", tags=["ato-response"])

classifier = ATOLetterClassifier()
drafter = ATOResponseDrafter()


class UpdateAtoResponseRequest(BaseModel):
    title: str | None = None
    content_md: str | None = None


def _extract_text(file_bytes: bytes) -> str:
    import io

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


@router.get("")
async def list_ato_responses(client=Depends(get_current_client), db=Depends(get_db)):
    return await asyncio.to_thread(
        db.documents.list_for_client, client["id"], "ato_response"
    )


@router.post("/upload")
async def upload_ato_letter(
    file: UploadFile,
    engagement_id: str | None = Form(default=None),
    client_ref: str | None = Form(default=None),
    client=Depends(get_current_client),
    db=Depends(get_db),
):
    file_bytes = await file.read()

    # Reject a spoofed engagement_id that belongs to another tenant.
    await ensure_engagement_owned(db, client["id"], engagement_id)

    extracted_text = _extract_text(file_bytes)

    classification = await classifier.classify(extracted_text)
    handler = get_handler(classification["letter_type"])
    strategy = handler.get_strategy(classification)
    # Task D1: inject the advisory per-client profile (business_type/state/
    # firm_style) into the drafter prompt so the letter is tuned to the firm.
    draft = await drafter.draft(
        classification=classification,
        strategy=strategy,
        original_letter=extracted_text,
        client_profile=build_client_profile(client),
        client_id=client["id"],
    )

    # Attribution fix (Phase 2): the ATO upload previously dropped client_ref +
    # engagement_id entirely. Persist BOTH on the document so ATO responses are
    # attributed to a real engagement/end-client like queries and generated
    # documents. Mirror query/documents' best-effort firm_clients.upsert so the
    # end-client register grows organically (never blocks the draft).
    await register_firm_client(db, client["id"], client_ref)

    result = await asyncio.to_thread(
        db.documents.insert,
        {
            "client_id": client["id"],
            "document_type": "ato_response",
            "title": f"ATO Response - {classification['letter_type']}",
            "content_md": draft["response_letter"],
            # Phase 5: persist the classified letter type structurally (not just
            # in the free-text title) so provenance is traceable and the
            # per-subtype template can be resolved.
            "ato_letter_type": classification["letter_type"],
            "client_ref": client_ref,
            "engagement_id": engagement_id,
            "created_by_user_id": client.get("user_id"),
        },
    )

    return {
        "document_id": result["id"],
        "classification": classification,
        "handler_result": strategy,
        "draft_response": draft["response_letter"],
        "deadline_days": classification.get("deadline_days"),
    }


@router.get("/{document_id}")
async def get_ato_response(document_id: str, client=Depends(get_current_client), db=Depends(get_db)):
    result = await asyncio.to_thread(db.documents.get_for_client, client["id"], document_id)
    if not result:
        raise HTTPException(status_code=404, detail="Correspondence not found")
    return result


@router.post("/{document_id}/approve")
async def approve_ato_response(
    document_id: str, client=Depends(require_permission("ato_response.approve")), db=Depends(get_db)
):
    # Ownership-scoped: only the owning client's document is updated.
    doc = await asyncio.to_thread(db.documents.get_for_client, client["id"], document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Correspondence not found")
    await asyncio.to_thread(
        db.documents.update_status, client["id"], document_id, "approved", {"approved_at": "now()"}
    )
    return {"status": "approved"}


@router.patch("/{document_id}")
async def update_ato_response(
    document_id: str,
    body: UpdateAtoResponseRequest,
    client=Depends(get_current_client),
    db=Depends(get_db),
):
    """Full-content edit of an ATO response (``content_md`` and/or ``title``),
    setting ``edited_at = now()``. ATO rows live in the ``documents`` table with
    ``document_type='ato_response'``; ownership is enforced via the ATO-scoped
    ``get_for_client`` (404 for a foreign or non-ATO doc). At least one field
    required (else 400)."""
    fields: dict = {}
    if body.title is not None:
        fields["title"] = body.title
    if body.content_md is not None:
        fields["content_md"] = body.content_md
    if not fields:
        raise HTTPException(
            status_code=400, detail="Provide at least one of title, content_md"
        )

    doc = await asyncio.to_thread(db.documents.get_for_client, client["id"], document_id)
    if not doc or doc.get("document_type") != "ato_response":
        raise HTTPException(status_code=404, detail="Correspondence not found")

    return await asyncio.to_thread(
        db.documents.update, client["id"], document_id, fields
    )


@router.delete("/{document_id}")
async def delete_ato_response(
    document_id: str, client=Depends(get_current_client), db=Depends(get_db)
):
    """Hard-delete an ATO response (a ``documents`` row with
    ``document_type='ato_response'``), scoped by client_id (404 for a foreign or
    non-ATO doc). Returns 409 if the row is FK-referenced (no cascade)."""
    doc = await asyncio.to_thread(db.documents.get_for_client, client["id"], document_id)
    if not doc or doc.get("document_type") != "ato_response":
        raise HTTPException(status_code=404, detail="Correspondence not found")
    is_own_work = doc.get("created_by_user_id") == client.get("user_id")
    if not is_own_work and not has_permission(client.get("role", "owner"), "work.delete_any"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    try:
        await asyncio.to_thread(db.documents.delete, client["id"], document_id)
    except psycopg2.IntegrityError as e:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete: this correspondence is referenced by another record.",
        ) from e
    return {"status": "deleted", "document_id": document_id}
