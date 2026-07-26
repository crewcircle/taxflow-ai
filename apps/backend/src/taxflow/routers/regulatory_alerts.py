import asyncio

from fastapi import APIRouter, Depends

from taxflow.db import get_db
from taxflow.middleware.auth import get_current_client

router = APIRouter(prefix="/regulatory-alerts", tags=["regulatory-alerts"])


@router.get("")
async def list_regulatory_alerts(_client=Depends(get_current_client), db=Depends(get_db)):
    """Recent regulatory alerts - global feed, not scoped to a client."""
    return await asyncio.to_thread(db.regulatory_alerts.list_recent, 50)


# --- "seen" cursor: server-side per-user, not per-browser localStorage -------
#
# Business audit P2 (Persona 3): every other notification kind already has
# server-side read state (notifications.read_at); the regulatory feed's
# "seen" marker was the one holdout still living in localStorage, so it reset
# on a new device/browser and never followed the user. This moves it onto
# users.regulatory_alerts_seen_at (048).
@router.get("/seen")
async def get_regulatory_alerts_seen(client=Depends(get_current_client)):
    return {"seen_at": client.get("regulatory_alerts_seen_at")}


@router.post("/seen")
async def mark_regulatory_alerts_seen(client=Depends(get_current_client), db=Depends(get_db)):
    await asyncio.to_thread(db.users.mark_regulatory_alerts_seen, client["user_id"])
    return {"seen_at": "now"}
