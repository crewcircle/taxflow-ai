import asyncio

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel

from taxflow.db import get_db
from taxflow.middleware.auth import get_current_client, require_permission
from taxflow.services.knowledge.embedder import embed

router = APIRouter(prefix="/firm-knowledge", tags=["firm-knowledge"])


class FromTextRequest(BaseModel):
    title: str
    content: str


class UpdateFirmKnowledgeRequest(BaseModel):
    content: str


class CreateSuggestionRequest(BaseModel):
    title: str
    content: str
    source_query_id: str | None = None
    source_document_id: str | None = None
    reason: str | None = None


class AssignSuggestionRequest(BaseModel):
    user_id: str | None = None


@router.get("")
async def list_firm_knowledge(client=Depends(get_current_client), db=Depends(get_db)):
    return await asyncio.to_thread(db.firm_knowledge.list_for_client, client["id"])


# --- Learning loop: approval-gated suggestions (Task C5) ---------------------
# CRITICAL: these /suggestions... routes MUST be declared ABOVE the
# @router.get("/{knowledge_id}") wildcard below. FastAPI matches routes in
# declaration order, so if /{knowledge_id} came first it would capture
# GET /firm-knowledge/suggestions as knowledge_id="suggestions".
@router.get("/suggestions")
async def list_suggestions(
    status: str | None = None,
    client=Depends(get_current_client),
    db=Depends(get_db),
):
    return await asyncio.to_thread(
        db.knowledge_suggestions.list_for_client, client["id"], status
    )


@router.post("/suggestions")
async def create_suggestion(
    body: CreateSuggestionRequest,
    client=Depends(get_current_client),
    db=Depends(get_db),
):
    """Create a PENDING knowledge suggestion (approval-gated learning loop).

    Backs the dashboard "Suggest for Firm Knowledge" promote button. Nothing is
    written to the authoritative firm_knowledge store here — a partner must
    approve the suggestion first. Client-scoped via get_current_client. When a
    source_query_id is provided it must belong to the current client (404
    otherwise).

    De-dup: this is one of TWO independent paths into a suggestion (the other
    is the automatic thumbs-up in routers/query.py) - both insert through
    ``insert_or_get_pending``, which relies on a DB-level partial unique index
    rather than a check-then-act read, so the two paths can't race each other
    into creating two pending suggestions for the same answer.
    """
    title = body.title.strip()
    content = body.content.strip()
    if not title or not content:
        raise HTTPException(status_code=400, detail="title and content are required")

    if body.source_query_id:
        owned = await asyncio.to_thread(
            db.queries.get_for_client, client["id"], body.source_query_id
        )
        if not owned:
            raise HTTPException(status_code=404, detail="Query not found")

    result = await asyncio.to_thread(
        db.knowledge_suggestions.insert_or_get_pending,
        {
            "client_id": client["id"],
            "source_query_id": body.source_query_id,
            "source_document_id": body.source_document_id,
            "title": title,
            "content": content,
            "reason": body.reason or "manual_promote",
        },
    )
    return result


@router.post("/suggestions/{suggestion_id}/assign")
async def assign_suggestion(
    suggestion_id: str,
    body: AssignSuggestionRequest,
    client=Depends(get_current_client),
    db=Depends(get_db),
):
    """Route a pending suggestion to an explicit reviewer rather than leaving
    it for "whoever notices the badge". ``user_id`` must be an active Owner on
    this client's roster (the only role that can ever approve/reject - see
    rbac.PERMISSIONS["knowledge.approve"]), so assignment can never point to
    someone who isn't allowed to act on it. Pass ``user_id: null`` to
    unassign. Client-scoped and pending-only, like approve/reject."""
    if body.user_id:
        roster = await asyncio.to_thread(db.users.list_for_client, client["id"])
        assignee = next((u for u in roster if u["id"] == body.user_id), None)
        if not assignee:
            raise HTTPException(status_code=404, detail="User not found on this firm's roster")
        if assignee["role"] != "owner":
            raise HTTPException(
                status_code=400,
                detail="Suggestions can only be assigned to an Owner - only Owners can approve or reject them",
            )

    result = await asyncio.to_thread(
        db.knowledge_suggestions.assign,
        client["id"],
        suggestion_id,
        body.user_id,
        client.get("user_id"),
    )
    if result is None:
        existing = await asyncio.to_thread(
            db.knowledge_suggestions.get_for_client, client["id"], suggestion_id
        )
        if not existing:
            raise HTTPException(status_code=404, detail="Not found")
        raise HTTPException(status_code=409, detail="Suggestion already decided")
    return result


@router.post("/suggestions/{suggestion_id}/approve")
async def approve_suggestion(
    suggestion_id: str, client=Depends(require_permission("knowledge.approve")), db=Depends(get_db)
):
    """Approve a PENDING suggestion into the authoritative firm_knowledge store:
    embed its content, then atomically claim the suggestion (pending→approved),
    insert the firm_knowledge note, and record the firm_knowledge_id — all in one
    transaction. Client-scoped, pending-only and idempotent: approving an
    already-decided suggestion (or a concurrent double-approve) is a 409 and does
    NOT insert a second firm_knowledge row."""
    suggestion = await asyncio.to_thread(
        db.knowledge_suggestions.get_for_client, client["id"], suggestion_id
    )
    if not suggestion:
        raise HTTPException(status_code=404, detail="Not found")
    if suggestion["status"] != "pending":
        raise HTTPException(status_code=409, detail="Suggestion already decided")

    embedding = await embed(suggestion["content"])
    result = await asyncio.to_thread(
        db.knowledge_suggestions.approve,
        client["id"],
        suggestion_id,
        {
            "client_id": client["id"],
            "file_name": suggestion["title"],
            "file_type": "note",
            "content": suggestion["content"],
            "embedding": embedding,
        },
        client.get("business_name") or client.get("email"),
    )
    if result is None:
        # Claimed by a concurrent request between our read and the atomic claim.
        raise HTTPException(status_code=409, detail="Suggestion already decided")
    return result


@router.post("/suggestions/{suggestion_id}/reject")
async def reject_suggestion(
    suggestion_id: str, client=Depends(require_permission("knowledge.approve")), db=Depends(get_db)
):
    """Reject a PENDING suggestion (status only — nothing is written to
    firm_knowledge). Client-scoped, pending-only and idempotent: rejecting an
    already-decided suggestion is a 409."""
    suggestion = await asyncio.to_thread(
        db.knowledge_suggestions.get_for_client, client["id"], suggestion_id
    )
    if not suggestion:
        raise HTTPException(status_code=404, detail="Not found")
    if suggestion["status"] != "pending":
        raise HTTPException(status_code=409, detail="Suggestion already decided")

    result = await asyncio.to_thread(
        db.knowledge_suggestions.set_decision,
        client["id"],
        suggestion_id,
        "rejected",
        {
            "decided_by": client.get("business_name") or client.get("email"),
            "decided_at": "now()",
        },
    )
    if result is None:
        raise HTTPException(status_code=409, detail="Suggestion already decided")
    return result


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
    deleted = await asyncio.to_thread(
        db.firm_knowledge.delete, client["id"], knowledge_id
    )
    if not deleted:
        # Missing or foreign-owned — the SQL scoping already blocked any
        # cross-tenant delete; surface 404 instead of a false success.
        raise HTTPException(status_code=404, detail="Firm knowledge not found")
    return {"status": "deleted"}


@router.patch("/{knowledge_id}")
async def update_firm_knowledge(
    knowledge_id: str,
    body: UpdateFirmKnowledgeRequest,
    client=Depends(get_current_client),
    db=Depends(get_db),
):
    """Edit a firm-knowledge note's content in-app. Re-runs ``embed(content)``
    before the UPDATE so the stored embedding stays consistent with the edited
    text (retrieval would otherwise match against the old vector). Client-scoped
    (404 for a foreign note)."""
    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Content cannot be empty")

    owned = await asyncio.to_thread(
        db.firm_knowledge.get_for_client, client["id"], knowledge_id
    )
    if not owned:
        raise HTTPException(status_code=404, detail="Not found")

    embedding = await embed(content)
    return await asyncio.to_thread(
        db.firm_knowledge.update, client["id"], knowledge_id, content, embedding
    )
