from datetime import datetime, timezone

import psycopg2
from fastapi import APIRouter

from taxflow.config import settings
from taxflow.scheduler import is_running

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    try:
        conn = psycopg2.connect(settings.DATABASE_URL, connect_timeout=2)
        conn.cursor().execute("SELECT 1")
        conn.close()
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
