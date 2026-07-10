from fastapi import APIRouter, Depends

from taxflow.db import get_db
from taxflow.middleware.auth import get_current_client

router = APIRouter(prefix="/regulatory-alerts", tags=["regulatory-alerts"])


@router.get("")
async def list_regulatory_alerts(_client=Depends(get_current_client), db=Depends(get_db)):
    """Recent regulatory alerts - global feed, not scoped to a client."""
    result = (
        db.table("regulatory_alerts")
        .select("id, source, alert_type, title, summary, url, detected_at")
        .order("detected_at", desc=True)
        .limit(50)
        .execute()
    )
    return result.data
