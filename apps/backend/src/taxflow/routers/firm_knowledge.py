import asyncio

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel

from taxflow.db import get_db
from taxflow.middleware.auth import get_current_client
from taxflow.services.knowledge.embedder import embed

router = APIRouter(prefix="/firm-knowledge", tags=["firm-knowledge"])


class FromTextRequest(BaseModel):
    title: str
    content: str


@router.get("")
async def list_firm_knowledge(client=Depends(get_current_client), db=Depends(get_db)):
    return await asyncio.to_thread(db.firm_knowledge.list_for_client, client["id"])


@router.get("/{knowledge_id}")
async def get_firm_knowledge(knowledge_id: str, client=Depends(get_current_client), db=Depends(get_db)):
    result = await asyncio.to_thread(
        db.firm_knowledge.get_for_client, client["id"], knowledge_id
    )
    if not result:
        raise HTTPException(status_code=404, detail="Not found")
    return result


@router.post("/from-text")
async def create_firm_knowledge_from_text(
    body: FromTextRequest, client=Depends(get_current_client), db=Depends(get_db)
):
    """Save a research answer (or other free text) directly as a Firm Knowledge
    entry, bypassing the file-upload path - used by the "save this answer"
    suggestion prompt shown after a client asks a repeated question."""
    title = body.title.strip() or "Untitled note"
    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Content cannot be empty")

    embedding = await embed(content)
    result = await asyncio.to_thread(
        db.firm_knowledge.insert,
        {
            "client_id": client["id"],
            "file_name": title,
            "file_type": "note",
            "content": content,
            "embedding": embedding,
        },
    )
    return {"id": result["id"], "file_name": title}


@router.post("/upload")
async def upload_firm_knowledge(file: UploadFile, client=Depends(get_current_client), db=Depends(get_db)):
    if client.get("is_demo"):
        raise HTTPException(status_code=403, detail="File uploads are disabled for the demo account")

    file_bytes = await file.read()
    file_type = (file.filename or "").rsplit(".", 1)[-1].lower()

    if file_type not in ("pdf", "docx", "txt"):
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file_type}")

    if file_type == "txt":
        content = file_bytes.decode("utf-8", errors="ignore")
    elif file_type == "pdf":
        import io

        import pdfplumber

        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            content = "\n".join(page.extract_text() or "" for page in pdf.pages)
    else:  # docx
        import io

        from docx import Document as DocxDocument

        content = "\n".join(p.text for p in DocxDocument(io.BytesIO(file_bytes)).paragraphs)

    embedding = await embed(content)
    result = await asyncio.to_thread(
        db.firm_knowledge.insert,
        {
            "client_id": client["id"],
            "file_name": file.filename,
            "file_type": file_type,
            "content": content,
            "embedding": embedding,
        },
    )
    return {"id": result["id"], "file_name": file.filename}


@router.delete("/{knowledge_id}")
async def delete_firm_knowledge(knowledge_id: str, client=Depends(get_current_client), db=Depends(get_db)):
    await asyncio.to_thread(db.firm_knowledge.delete, client["id"], knowledge_id)
    return {"status": "deleted"}
