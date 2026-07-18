from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from taxflow.config import settings
from taxflow.db import get_db
from taxflow.scheduler import is_running

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(db=Depends(get_db)):
    try:
        # Fast-fail check: pool connections are already warm, so borrowing +
        # SELECT 1 returns in well under the old connect_timeout=2 budget.
        db.health.ping()
        database_status = "connected"
    except Exception as e:  # noqa: BLE001
        database_status = f"error: {e}"

    return {
        "status": "ok",
        "version": "0.1.0",
        "environment": settings.ENVIRONMENT,
        "database": database_status,
        "scheduler": "running" if is_running() else "stopped",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
