from fastapi import APIRouter, Depends, HTTPException, UploadFile

from taxflow.db import get_db
from taxflow.middleware.auth import get_current_client
from taxflow.services.knowledge.embedder import embed

router = APIRouter(prefix="/firm-knowledge", tags=["firm-knowledge"])


@router.post("/upload")
async def upload_firm_knowledge(file: UploadFile, client=Depends(get_current_client), db=Depends(get_db)):
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
    result = (
        db.table("firm_knowledge")
        .insert(
            {
                "client_id": client["id"],
                "file_name": file.filename,
                "file_type": file_type,
                "content": content,
                "embedding": embedding,
            }
        )
        .execute()
    )
    return {"id": result.data[0]["id"], "file_name": file.filename}


@router.delete("/{knowledge_id}")
async def delete_firm_knowledge(knowledge_id: str, client=Depends(get_current_client), db=Depends(get_db)):
    db.table("firm_knowledge").delete().eq("id", knowledge_id).eq("client_id", client["id"]).execute()
    return {"status": "deleted"}
