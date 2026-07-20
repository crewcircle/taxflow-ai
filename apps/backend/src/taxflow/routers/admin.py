"""Operator-global observability endpoints (Task 2b).

``GET /admin/stats?window=7d`` returns the aggregate produced by
``QueriesRepo.stats`` over the trailing window. These endpoints are NOT
client-scoped: they expose operator-global metrics and are gated by the shared
admin token (:func:`taxflow.middleware.admin.require_admin`) rather than
``get_current_client``. No raw SQL lives here — all aggregation is in the repo.
"""

import asyncio
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from taxflow.db import get_db
from taxflow.middleware.admin import require_admin

router = APIRouter(prefix="/admin", tags=["admin"])

# Cap the window so an operator can't request an unbounded aggregate. Must be
# >= 365 days to cover the dashboard's ``12m`` window (Task 3b).
_MAX_WINDOW = timedelta(days=366)
# A month is treated as 30 days for window parsing (12m -> 360 days, under cap).
_DAYS_PER_MONTH = 30
_WINDOW_RE = re.compile(r"^(\d+)([dm])$")


def parse_window(window: str) -> timedelta:
    """Parse a window string like ``7d``/``30d``/``90d``/``12m`` into a
    ``timedelta``. ``d`` = days, ``m`` = (30-day) months. The result is capped at
    ``_MAX_WINDOW`` (>=365 days). Raises ``HTTPException(400)`` on a bad format."""
    match = _WINDOW_RE.match(window or "")
    if not match:
        raise HTTPException(status_code=400, detail=f"Invalid window: {window!r}")
    amount = int(match.group(1))
    unit = match.group(2)
    if amount <= 0:
        raise HTTPException(status_code=400, detail=f"Invalid window: {window!r}")
    days = amount if unit == "d" else amount * _DAYS_PER_MONTH
    delta = timedelta(days=days)
    return min(delta, _MAX_WINDOW)


@router.get("/stats")
async def admin_stats(
    window: str = "7d",
    db=Depends(get_db),
    _=Depends(require_admin),
):
    """Operator-global query stats over the trailing ``window`` (default 7d)."""
    delta = parse_window(window)
    start = datetime.now(timezone.utc) - delta
    # end defaults to now inside the repo (end=None -> up to now).
    return await asyncio.to_thread(db.queries.stats, start)
