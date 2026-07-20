"""Shared best-effort helpers used across job-start routers.

Kept deliberately small: relational access still goes through ``db`` (the
repositories facade), so this module holds only cross-router glue, no SQL.
"""
import asyncio

from fastapi import HTTPException


async def ensure_engagement_owned(db, client_id: str, engagement_id: str | None) -> None:
    """Reject a supplied ``engagement_id`` that isn't the caller's.

    Migration 039 only enforces ``REFERENCES engagements(id)`` — Postgres checks
    the row exists but NOT that its ``client_id`` matches the tenant. So a
    tampered request could attach this tenant's query/document/ATO row to
    another tenant's engagement UUID. We close that hole in app code (the only
    tenant boundary) by confirming the engagement is visible under the caller's
    ``client_id`` before any insert; an unknown/foreign id is a 404.
    """
    if not engagement_id:
        return
    row = await asyncio.to_thread(
        db.engagements.get_for_client, client_id, engagement_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Engagement not found")


async def register_firm_client(db, client_id: str, client_ref: str | None) -> None:
    """Best-effort upsert of an end-client into the firm's register.

    The client register (Settings audit follow-up) grows organically from real
    use rather than requiring firms to pre-seed a client list. ``upsert`` is a
    no-op on repeat names (``ON CONFLICT DO NOTHING``) and must never block the
    job it accompanies — a failure here is swallowed so answering the query /
    saving the document / drafting the ATO reply always proceeds.
    """
    if not client_ref:
        return
    try:
        await asyncio.to_thread(db.firm_clients.upsert, client_id, client_ref)
    except Exception:  # noqa: BLE001 - never block the primary job
        pass
