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


def _last_activity(row: dict) -> tuple[str | None, str | None]:
    """Pick the most recent of a row's three activity timestamps and label it.
    Returns (iso_timestamp_or_None, type_or_None)."""
    candidates = [
        (row.get("last_question_at"), "question"),
        (row.get("last_document_at"), "document"),
        (row.get("last_comment_at"), "comment"),
    ]
    candidates = [(ts, kind) for ts, kind in candidates if ts is not None]
    if not candidates:
        return None, None
    ts, kind = max(candidates, key=lambda pair: pair[0])
    return ts.isoformat(), kind


@router.get("/directory")
async def engagements_directory(client=Depends(get_current_client), db=Depends(get_db)):
    """Per-client rollup for the Clients & Engagements page: how many
    engagements each firm-client has, each one's last action (type + when),
    and whether anything needs attention (an unresolved comment or a pending
    re-research). Grouped in Python from one flat query - simpler than a
    nested SQL aggregate and the row count here is always small (one row per
    engagement for a single tenant)."""
    rows = await asyncio.to_thread(db.engagements.list_directory, client["id"])

    clients: dict[str, dict] = {}
    for row in rows:
        last_activity, last_activity_type = _last_activity(row)
        needs_attention = row["open_comment_count"] > 0 or row["pending_re_research_count"] > 0
        engagement = {
            "id": row["id"],
            "engagement_number": row["engagement_number"],
            "description": row["description"],
            "status": row["status"],
            "created_at": row["created_at"].isoformat(),
            "query_count": row["query_count"],
            "document_count": row["document_count"],
            "open_comment_count": row["open_comment_count"],
            "pending_re_research_count": row["pending_re_research_count"],
            "last_activity": last_activity,
            "last_activity_type": last_activity_type,
            "needs_attention": needs_attention,
        }
        fc_id = row["firm_client_id"]
        if fc_id not in clients:
            clients[fc_id] = {
                "firm_client_id": fc_id,
                "firm_client_name": row["firm_client_name"],
                "engagements": [],
            }
        clients[fc_id]["engagements"].append(engagement)

    result = []
    for client_row in clients.values():
        engagements = client_row["engagements"]
        activity_times = [e["last_activity"] for e in engagements if e["last_activity"]]
        result.append(
            {
                **client_row,
                "engagement_count": len(engagements),
                "needs_attention_count": sum(1 for e in engagements if e["needs_attention"]),
                "last_activity": max(activity_times) if activity_times else None,
            }
        )
    # Most-recently-active client first; ISO 8601 strings sort chronologically,
    # and "" (no activity) sorts after every real timestamp under reverse=True.
    result.sort(key=lambda c: c["last_activity"] or "", reverse=True)
    return result


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
