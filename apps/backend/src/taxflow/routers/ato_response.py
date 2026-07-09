import pdfplumber
from fastapi import APIRouter, Depends, HTTPException, UploadFile

from taxflow.db import get_db
from taxflow.middleware.auth import get_current_client
from taxflow.services.ato_correspondence.classifier import ATOLetterClassifier
from taxflow.services.ato_correspondence.drafter import ATOResponseDrafter
from taxflow.services.ato_correspondence.handlers import get_handler

router = APIRouter(prefix="/ato-response", tags=["ato-response"])

classifier = ATOLetterClassifier()
drafter = ATOResponseDrafter()


def _extract_text(file_bytes: bytes) -> str:
    import io

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


@router.get("")
async def list_ato_responses(client=Depends(get_current_client), db=Depends(get_db)):
    result = (
        db.table("documents")
        .select("id, title, status, created_at")
        .eq("client_id", client["id"])
        .eq("document_type", "ato_response")
        .order("created_at", desc=True)
        .execute()
    )
    return result.data


@router.post("/upload")
async def upload_ato_letter(file: UploadFile, client=Depends(get_current_client), db=Depends(get_db)):
    file_bytes = await file.read()
    extracted_text = _extract_text(file_bytes)

    classification = await classifier.classify(extracted_text)
    handler = get_handler(classification["letter_type"])
    strategy = handler.get_strategy(classification)
    draft = await drafter.draft(classification=classification, strategy=strategy, original_letter=extracted_text)

    result = (
        db.table("documents")
        .insert(
            {
                "client_id": client["id"],
                "document_type": "ato_response",
                "title": f"ATO Response - {classification['letter_type']}",
                "content_md": draft["response_letter"],
            }
        )
        .execute()
    )

    return {
        "document_id": result.data[0]["id"],
        "classification": classification,
        "handler_result": strategy,
        "draft_response": draft["response_letter"],
        "deadline_days": classification.get("deadline_days"),
    }


@router.get("/{document_id}")
async def get_ato_response(document_id: str, client=Depends(get_current_client), db=Depends(get_db)):
    result = db.table("documents").select("*").eq("id", document_id).eq("client_id", client["id"]).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Correspondence not found")
    return result.data[0]


@router.post("/{document_id}/approve")
async def approve_ato_response(document_id: str, client=Depends(get_current_client), db=Depends(get_db)):
    db.table("documents").update({"status": "approved", "approved_at": "now()"}).eq("id", document_id).eq(
        "client_id", client["id"]
    ).execute()
    return {"status": "approved"}
