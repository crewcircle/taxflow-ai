"""Notifications router (Task C2).

Polling-based delivery for async events (e.g. a feedback-triggered re-research
completing). SSE can't deliver a completion event after the query stream has
closed, so the dashboard polls these endpoints instead. Client-scoped via the
existing ``get_current_client`` dependency like every other router.
"""
import asyncio

from fastapi import APIRouter, Depends, HTTPException

from taxflow.db import get_db
from taxflow.middleware.auth import get_current_client

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(client=Depends(get_current_client), db=Depends(get_db)):
    """Recent notifications for the requesting client, newest first."""
    return await asyncio.to_thread(db.notifications.list_for_client, client["id"])


@router.post("/{notification_id}/read")
async def mark_notification_read(
    notification_id: str, client=Depends(get_current_client), db=Depends(get_db)
):
    """Mark a notification read. Scoped by client_id so a client can only mark
    its own notifications."""
    await asyncio.to_thread(db.notifications.mark_read, client["id"], notification_id)
    return {"id": notification_id, "read": True}


@router.delete("/{notification_id}")
async def delete_notification(
    notification_id: str, client=Depends(get_current_client), db=Depends(get_db)
):
    """Delete a notification. Scoped by client_id so a client can only delete
    its own notification. 404 when nothing owned was deleted (missing /
    foreign-owned) rather than reporting a false success."""
    deleted = await asyncio.to_thread(
        db.notifications.delete, client["id"], notification_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"status": "deleted", "id": notification_id}
