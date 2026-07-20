"""Phase 1 (Core): line/word-level annotations & comments API.

One polymorphic endpoint set backs BOTH generated documents and query answers.
``target_type`` selects which repo verifies ownership of ``target_id`` before
any read/write, mirroring ``submit_feedback`` (query.py): a target belonging to
another client returns 404 before touching the annotations table. ``client_id``
is ALWAYS forced from the auth context and never read from the request body.
"""
import asyncio
import hashlib

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from taxflow.db import get_db
from taxflow.middleware.auth import get_current_client

router = APIRouter(prefix="/annotations", tags=["annotations"])

# The allowed sets mirror the DB CHECK constraints in migration 038 exactly.
TARGET_TYPES = {"query_answer", "document"}
AUTHOR_KINDS = {"reviewer", "user"}


def source_hash(markdown: str | None) -> str:
    """Stable hash of the source markdown for stale-anchor detection.

    Computed identically here and on the client (SHA-256 hex, truncated). The
    GET response returns the current source hash so the client can compare it
    against each annotation's stored ``target_version``.
    """
    return hashlib.sha256((markdown or "").encode("utf-8")).hexdigest()[:16]


class AnnotationCreate(BaseModel):
    target_type: str
    target_id: str
    target_version: str
    block_index: int
    start_offset: int
    end_offset: int
    quoted_text: str
    author_kind: str
    body: str
    author_name: str | None = None
    parent_id: str | None = None


class AnnotationUpdate(BaseModel):
    body: str | None = None
    resolved: bool | None = None


async def _resolve_target(db, client_id: str, target_type: str, target_id: str) -> dict:
    """Verify the caller owns ``target_id`` and return the owning row.

    Branches on ``target_type`` to the matching ownership lookup. Raises 404 for
    an unknown type or a target owned by another client — the single tenant
    boundary for the polymorphic table.
    """
    if target_type == "query_answer":
        owned = await asyncio.to_thread(db.queries.get_for_client, client_id, target_id)
    elif target_type == "document":
        owned = await asyncio.to_thread(db.documents.get_for_client, client_id, target_id)
    else:
        raise HTTPException(status_code=422, detail="invalid target_type")
    if not owned:
        raise HTTPException(status_code=404, detail="Target not found")
    return owned


def _current_source(owned: dict, target_type: str) -> str | None:
    return owned.get("final_answer") if target_type == "query_answer" else owned.get("content_md")


@router.get("")
async def list_annotations(
    target_type: str,
    target_id: str,
    client=Depends(get_current_client),
    db=Depends(get_db),
):
    """List annotations on an owned target, plus the current source hash so the
    client can detect anchors that were computed against stale markdown."""
    if target_type not in TARGET_TYPES:
        raise HTTPException(status_code=422, detail="invalid target_type")

    owned = await _resolve_target(db, client["id"], target_type, target_id)
    annotations = await asyncio.to_thread(
        db.annotations.list_for_target, client["id"], target_type, target_id
    )
    return {
        "annotations": annotations,
        "source_hash": source_hash(_current_source(owned, target_type)),
    }


@router.post("", status_code=201)
async def create_annotation(
    body: AnnotationCreate,
    client=Depends(get_current_client),
    db=Depends(get_db),
):
    if body.target_type not in TARGET_TYPES:
        raise HTTPException(status_code=422, detail="invalid target_type")
    if body.author_kind not in AUTHOR_KINDS:
        raise HTTPException(status_code=422, detail="invalid author_kind")

    await _resolve_target(db, client["id"], body.target_type, body.target_id)

    # Reply validation: a reply's parent must belong to the SAME client AND the
    # SAME target (parent_id is only a self-FK, so nothing else stops a reply
    # from being coupled to another tenant's / another target's thread).
    if body.parent_id:
        parent = await asyncio.to_thread(
            db.annotations.get_for_client, client["id"], body.parent_id
        )
        if (
            not parent
            or parent["target_type"] != body.target_type
            or str(parent["target_id"]) != str(body.target_id)
        ):
            raise HTTPException(status_code=404, detail="Parent annotation not found")

    row = await asyncio.to_thread(
        db.annotations.insert,
        {
            # client_id is forced from the auth context, NEVER from the body.
            "client_id": client["id"],
            "target_type": body.target_type,
            "target_id": body.target_id,
            "target_version": body.target_version,
            "block_index": body.block_index,
            "start_offset": body.start_offset,
            "end_offset": body.end_offset,
            "quoted_text": body.quoted_text,
            "author_kind": body.author_kind,
            "author_name": body.author_name,
            "body": body.body,
            "parent_id": body.parent_id,
        },
    )
    return row


@router.patch("/{annotation_id}")
async def update_annotation(
    annotation_id: str,
    body: AnnotationUpdate,
    client=Depends(get_current_client),
    db=Depends(get_db),
):
    owned = await asyncio.to_thread(db.annotations.get_for_client, client["id"], annotation_id)
    if not owned:
        raise HTTPException(status_code=404, detail="Annotation not found")

    fields: dict = {}
    if body.body is not None:
        fields["body"] = body.body
    if body.resolved is not None:
        fields["resolved_at"] = "now()" if body.resolved else None
    if not fields:
        return owned

    updated = await asyncio.to_thread(
        db.annotations.update, client["id"], annotation_id, fields
    )
    return updated


@router.delete("/{annotation_id}", status_code=204)
async def delete_annotation(
    annotation_id: str,
    client=Depends(get_current_client),
    db=Depends(get_db),
):
    owned = await asyncio.to_thread(db.annotations.get_for_client, client["id"], annotation_id)
    if not owned:
        raise HTTPException(status_code=404, detail="Annotation not found")
    # Deleting a root comment cascades its replies via the parent self-FK.
    await asyncio.to_thread(db.annotations.delete, client["id"], annotation_id)
    return None
