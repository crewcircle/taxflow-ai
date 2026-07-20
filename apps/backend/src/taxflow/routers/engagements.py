"""Phase 2: first-class engagements API.

An engagement links the tenant (``client_id``, forced from the auth context and
NEVER read from the request body) to one of the firm's real end-clients
(``firm_client_id``). ``client_id`` scoping is the only tenant boundary — RLS is
service-role-only — so every repo call is scoped to ``client["id"]``.

``POST /engagements`` applies an app-layer default description when the caller
sends a blank one, so an engagement is never stored with an empty description
(the DB column is NOT NULL). ``db.engagements.create`` raises when the target
firm-client is unknown or belongs to another tenant; that surfaces as a 404 so a
caller cannot probe another tenant's firm-clients.
"""
import asyncio
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from taxflow.db import get_db
from taxflow.middleware.auth import get_current_client

router = APIRouter(prefix="/engagements", tags=["engagements"])


class EngagementCreate(BaseModel):
    firm_client_id: str
    description: str | None = None


def _default_description() -> str:
    """The one-click "General" default used when the picker sends no
    description — a dated general-research label, so the engagement always has a
    meaningful, non-empty description."""
    return f"General tax research — {date.today().isoformat()}"


@router.get("")
async def list_engagements(
    firm_client_id: str | None = None,
    status: str | None = None,
    client=Depends(get_current_client),
    db=Depends(get_db),
):
    """List the tenant's engagements, optionally filtered by end-client and/or
    status. Always scoped to the caller's ``client_id``."""
    return await asyncio.to_thread(
        db.engagements.list_for_client, client["id"], firm_client_id, status
    )


@router.post("", status_code=201)
async def create_engagement(
    body: EngagementCreate,
    client=Depends(get_current_client),
    db=Depends(get_db),
):
    # Apply the default ONLY when the description is blank; a non-blank
    # description is stored verbatim (surrounding whitespace preserved) — the
    # contract is "default when blank, otherwise pass through unchanged".
    description = body.description
    if description is None or description.strip() == "":
        description = _default_description()
    try:
        row = await asyncio.to_thread(
            db.engagements.create,
            client["id"],
            body.firm_client_id,
            description,
            client.get("email"),
        )
    except ValueError:
        # Unknown firm-client or one owned by another tenant — do not reveal
        # which; a foreign/unknown end-client is simply "not found".
        raise HTTPException(status_code=404, detail="Client not found")
    return row


@router.get("/{engagement_id}")
async def get_engagement(
    engagement_id: str,
    client=Depends(get_current_client),
    db=Depends(get_db),
):
    row = await asyncio.to_thread(
        db.engagements.get_for_client, client["id"], engagement_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Engagement not found")
    return row
