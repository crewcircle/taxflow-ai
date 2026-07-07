from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from taxflow.db import get_db
from taxflow.middleware.auth import get_current_client
from taxflow.services.export import generate_docx, generate_pdf

router = APIRouter(prefix="/documents", tags=["documents"])

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


@router.get("/templates")
async def list_templates():
    return [{"type": k, "label": v} for k, v in TEMPLATE_REGISTRY.items()]


@router.post("/generate")
async def generate_document(
    body: GenerateDocumentRequest, client=Depends(get_current_client), db=Depends(get_db)
):
    if body.document_type not in TEMPLATE_REGISTRY:
        raise HTTPException(status_code=400, detail=f"Unknown document_type: {body.document_type}")

    result = (
        db.table("documents")
        .insert(
            {
                "client_id": client["id"],
                "query_id": body.query_id,
                "document_type": body.document_type,
                "title": body.title,
                "content_md": body.content_md,
            }
        )
        .execute()
    )
    return result.data[0]


@router.get("/{document_id}/download")
async def download_document(document_id: str, fmt: str = "docx", client=Depends(get_current_client), db=Depends(get_db)):
    result = db.table("documents").select("*").eq("id", document_id).eq("client_id", client["id"]).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Document not found")

    doc = result.data[0]
    if fmt == "pdf":
        content = generate_pdf(doc["content_md"], doc["title"], client["business_name"], doc["created_at"])
        media_type = "application/pdf"
    else:
        content = generate_docx(doc["content_md"], doc["title"], client["business_name"], doc["created_at"])
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    return Response(content=content, media_type=media_type)
