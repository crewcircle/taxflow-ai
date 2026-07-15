from datetime import datetime, timezone

from fastapi import APIRouter

from taxflow.config import settings
from taxflow.db import get_pg_conn
from taxflow.scheduler import is_running

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    try:
        # Fast-fail check: pool connections are already warm, so borrowing +
        # SELECT 1 returns in well under the old connect_timeout=2 budget.
        with get_pg_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
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
