import asyncio

from fastapi import APIRouter, Depends

from taxflow.db import get_db
from taxflow.middleware.auth import get_current_client

router = APIRouter(prefix="/regulatory-alerts", tags=["regulatory-alerts"])


@router.get("")
async def list_regulatory_alerts(_client=Depends(get_current_client), db=Depends(get_db)):
    """Recent regulatory alerts - global feed, not scoped to a client."""
    return await asyncio.to_thread(db.regulatory_alerts.list_recent, 50)
