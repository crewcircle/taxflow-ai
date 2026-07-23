import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from taxflow import providers
from taxflow.db import get_db
from taxflow.middleware.auth import get_current_client, require_permission
from taxflow.ports.auth import AuthError
from taxflow.rbac import Role

router = APIRouter(prefix="/staff", tags=["staff"])


class StaffInvite(BaseModel):
    email: EmailStr
    role: Role = Role.STAFF
    display_name: str | None = None


class StaffRoleUpdate(BaseModel):
    role: Role


@router.get("")
async def list_staff(client=Depends(get_current_client), db=Depends(get_db)):
    """The firm's roster - visible to every role (not just Owner), so Staff
    can see who's on the team; only mutations are permission-gated."""
    return await asyncio.to_thread(db.users.list_for_client, client["id"])


@router.post("/invite", status_code=201)
async def invite_staff(
    body: StaffInvite,
    client=Depends(require_permission("staff.manage")),
    db=Depends(get_db),
):
    """Invite a new staff login: sends Supabase's own invite email (accept
    link), then creates the matching ``users`` row immediately so the roster
    shows the pending invite before the invitee ever logs in."""
    existing = await asyncio.to_thread(
        db.users.get_by_client_and_email, client["id"], body.email
    )
    if existing:
        raise HTTPException(status_code=409, detail="This email is already on the roster")

    try:
        identity = await asyncio.to_thread(providers.get_auth_port().invite_user, body.email)
    except AuthError as e:
        raise HTTPException(status_code=502, detail=f"Invite failed: {e}") from e

    return await asyncio.to_thread(
        db.users.create,
        identity.sub,
        client["id"],
        body.email,
        body.role.value,
        body.display_name,
        client["user_id"],
        "invited",
    )


@router.patch("/{user_id}")
async def update_staff_role(
    user_id: str,
    body: StaffRoleUpdate,
    client=Depends(require_permission("staff.manage")),
    db=Depends(get_db),
):
    """Change a staff member's role. Refuses to drop the firm's last active
    Owner - that would lock the firm out of billing/staff management with no
    way back in."""
    target = await asyncio.to_thread(db.users.get_by_id, user_id)
    if not target or target["client_id"] != client["id"]:
        raise HTTPException(status_code=404, detail="Staff member not found")

    if target["role"] == Role.OWNER.value and body.role != Role.OWNER:
        owner_count = await asyncio.to_thread(db.users.count_active_owners, client["id"])
        if owner_count <= 1:
            raise HTTPException(
                status_code=409, detail="Cannot demote the firm's last remaining Owner"
            )

    updated = await asyncio.to_thread(
        db.users.update_role, client["id"], user_id, body.role.value
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Staff member not found")
    return updated


@router.delete("/{user_id}")
async def remove_staff(
    user_id: str,
    client=Depends(require_permission("staff.manage")),
    db=Depends(get_db),
):
    """Soft-remove a staff member (status='removed') - never a hard delete,
    so their ``created_by_user_id`` attribution on past work stays intact.
    A removed user's next request 403s immediately (see get_current_client),
    even with a still-valid Supabase JWT. Refuses to remove the firm's last
    active Owner for the same lockout reason as role changes above."""
    target = await asyncio.to_thread(db.users.get_by_id, user_id)
    if not target or target["client_id"] != client["id"]:
        raise HTTPException(status_code=404, detail="Staff member not found")

    if target["role"] == Role.OWNER.value:
        owner_count = await asyncio.to_thread(db.users.count_active_owners, client["id"])
        if owner_count <= 1:
            raise HTTPException(
                status_code=409, detail="Cannot remove the firm's last remaining Owner"
            )

    updated = await asyncio.to_thread(db.users.set_status, client["id"], user_id, "removed")
    if not updated:
        raise HTTPException(status_code=404, detail="Staff member not found")
    return {"status": "removed"}
