"""Shared best-effort helpers used across job-start routers.

Kept deliberately small: relational access still goes through ``db`` (the
repositories facade), so this module holds only cross-router glue, no SQL.
"""
import asyncio
import logging

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# Must match scripts/backfill_engagements.py's UNATTRIBUTED_NAME exactly: new
# un-attributed work (this module) and the one-time backfill of historical
# orphans both need to land under the SAME firm_clients row per tenant, not
# two inconsistent buckets. The live engagement uses its own "General"
# description (not the backfill's "General (backfilled)") so the two
# populations stay visually distinguishable in the engagement picker/history.
UNATTRIBUTED_FIRM_CLIENT_NAME = "General / Unattributed"
LIVE_UNATTRIBUTED_DESCRIPTION = "General"


async def resolve_or_default_engagement(db, client_id: str, engagement_id: str | None) -> dict:
    """Resolve ``engagement_id`` to ``{"engagement_id", "firm_client_id"}``,
    validating tenant ownership - or, if omitted, get-or-create the tenant's
    "Unattributed" bucket so every NEW query/document is always attributed to
    a real engagement/firm_client (audit finding: an orphaned query/document
    with no client_ref and no engagement_id used to be a normal, permitted
    state). Historical orphans are handled separately by the one-time
    ``scripts/backfill_engagements.py`` step; this only covers new writes.

    Migration 039 only enforces ``REFERENCES engagements(id)`` — Postgres
    checks the row exists but NOT that its ``client_id`` matches the tenant.
    So a tampered request could attach this tenant's query/document/ATO row
    to another tenant's engagement UUID; a supplied ``engagement_id`` is only
    ever trusted after ``get_for_client`` confirms it's visible under the
    caller's own ``client_id`` (an unknown/foreign id 404s).

    Concurrent-create note: the get-or-create for the live "General" engagement
    is a look-up-then-create, not a single atomic statement (unlike
    ``EngagementsRepo.create``'s own row-locked sequence-number allocation) -
    two simultaneous first-ever un-attributed writes for the same tenant could
    rarely create two "General" engagements. Both would still be valid,
    correctly-attributed engagements under the same firm_client; this is a
    cosmetic duplication, not a correctness bug, and not worth a locking
    scheme for how rarely it can occur.
    """
    if engagement_id:
        row = await asyncio.to_thread(db.engagements.get_for_client, client_id, engagement_id)
        if not row:
            raise HTTPException(status_code=404, detail="Engagement not found")
        return {"engagement_id": row["id"], "firm_client_id": row["firm_client_id"]}

    firm_client = await asyncio.to_thread(
        db.firm_clients.create, client_id, UNATTRIBUTED_FIRM_CLIENT_NAME
    )
    engagement = await asyncio.to_thread(
        db.engagements.get_by_firm_client_and_description,
        client_id,
        firm_client["id"],
        LIVE_UNATTRIBUTED_DESCRIPTION,
    )
    if not engagement:
        engagement = await asyncio.to_thread(
            db.engagements.create, client_id, firm_client["id"], LIVE_UNATTRIBUTED_DESCRIPTION
        )
    return {"engagement_id": engagement["id"], "firm_client_id": firm_client["id"]}


async def register_firm_client(db, client_id: str, client_ref: str | None) -> None:
    """Best-effort upsert of an end-client into the firm's register.

    The client register (Settings audit follow-up) grows organically from real
    use rather than requiring firms to pre-seed a client list. ``upsert`` is a
    no-op on repeat names (``ON CONFLICT DO NOTHING``) and must never block the
    job it accompanies — a failure here is logged, not raised, so answering
    the query / saving the document / drafting the ATO reply always proceeds.
    A silently-dropped failure here previously left a client in
    ``documents.client_ref``/``queries.client_ref`` with no matching row in
    ``firm_clients``, which is exactly what made the client picker unable to
    find real, existing clients — logging it is what makes that gap visible
    instead of invisible.
    """
    if not client_ref:
        return
    try:
        await asyncio.to_thread(db.firm_clients.upsert, client_id, client_ref)
    except Exception:
        logger.warning(
            "register_firm_client failed for client_id=%s client_ref=%r",
            client_id,
            client_ref,
            exc_info=True,
        )
