import asyncio

import pdfplumber
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile

from taxflow.db import get_db
from taxflow.middleware.auth import get_current_client
from taxflow.services.ato_correspondence.classifier import ATOLetterClassifier
from taxflow.services.ato_correspondence.drafter import ATOResponseDrafter
from taxflow.services.ato_correspondence.handlers import get_handler
from taxflow.services.agents.research import build_client_profile

router = APIRouter(prefix="/ato-response", tags=["ato-response"])

classifier = ATOLetterClassifier()
drafter = ATOResponseDrafter()


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
    )

    # Attribution fix (Phase 2): the ATO upload previously dropped client_ref +
    # engagement_id entirely. Persist BOTH on the document so ATO responses are
    # attributed to a real engagement/end-client like queries and generated
    # documents. Mirror query/documents' best-effort firm_clients.upsert so the
    # end-client register grows organically (never blocks the draft).
    if client_ref:
        try:
            await asyncio.to_thread(db.firm_clients.upsert, client["id"], client_ref)
        except Exception:  # noqa: BLE001 - never block returning the draft
            pass

    result = await asyncio.to_thread(
        db.documents.insert,
        {
            "client_id": client["id"],
            "document_type": "ato_response",
            "title": f"ATO Response - {classification['letter_type']}",
            "content_md": draft["response_letter"],
            "client_ref": client_ref,
            "engagement_id": engagement_id,
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
async def approve_ato_response(document_id: str, client=Depends(get_current_client), db=Depends(get_db)):
    # Ownership-scoped: only the owning client's document is updated.
    doc = await asyncio.to_thread(db.documents.get_for_client, client["id"], document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Correspondence not found")
    await asyncio.to_thread(
        db.documents.update_status, client["id"], document_id, "approved", {"approved_at": "now()"}
    )
    return {"status": "approved"}
