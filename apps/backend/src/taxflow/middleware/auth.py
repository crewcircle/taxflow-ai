import asyncio
from typing import Callable

from fastapi import Depends, HTTPException, Request

from taxflow import providers
from taxflow.ports.auth import AuthError
from taxflow.rbac import has_permission


async def get_current_client(request: Request) -> dict:
    """Validate the bearer token via the AuthPort and return the client row,
    merged with the caller's ``role``/``user_id`` from the ``users`` table.

    Missing/malformed bearer → 401; invalid token (AuthError) → 401; a
    removed staff account → 403 (this is what makes staff removal effective
    without needing to revoke an already-issued Supabase JWT). A valid token
    for a brand-new signup (OAuth or otherwise) auto-provisions a minimal
    trial account + Owner user, mirroring what /api/signup does for the
    columns it doesn't collect explicitly.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = auth_header.split(" ", 1)[1]

    try:
        identity = providers.get_auth_port().validate_token(token)
    except AuthError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}") from e

    client = await asyncio.to_thread(_get_or_provision_client, identity)
    request.state.client_id = client["id"]
    request.state.user_id = client["user_id"]
    return client


def _get_or_provision_client(identity) -> dict:
    """Return the client row for ``identity`` (merged with ``role``/``user_id``),
    provisioning a client+user or a missing user row as needed.

    Lookup order:
      1. ``users.get_by_id(identity.sub)`` — the real, stable identity path.
      2. Fallback: ``clients.get_by_email`` for the pre-migration-043 gap
         (an owner logging in before the backfill join found them) — on a
         hit, lazily create the missing ``users`` row so the gap self-heals
         and never repeats.
      3. Neither hits: brand-new signup (OAuth or otherwise) — create the
         ``clients`` row exactly as before, plus a ``users`` row alongside it.
    """
    db = providers.get_relational_data()
    user = db.users.get_by_id(identity.sub)
    if user:
        if user["status"] == "removed":
            raise HTTPException(status_code=403, detail="This account has been removed")
        client = db.clients.get_by_id(user["client_id"])
        return {**client, "role": user["role"], "user_id": user["id"]}

    client = db.clients.get_by_email(identity.email)
    if client:
        # Pre-043 gap (or a user created after the migration's join ran):
        # self-heal by creating the missing Owner row now.
        user = db.users.create(identity.sub, client["id"], identity.email, role="owner")
        return {**client, "role": user["role"], "user_id": user["id"]}

    metadata = identity.metadata or {}
    business_name = (
        metadata.get("full_name")
        or metadata.get("name")
        or identity.email.split("@")[0]
    )
    client = db.clients.create(
        {
            "business_name": business_name,
            "email": identity.email,
            "business_type": "other",
            "suburb": "",
            "state": "NSW",
        }
    )
    db.trials.create(client["id"])
    user = db.users.create(identity.sub, client["id"], identity.email, role="owner")
    return {**client, "role": user["role"], "user_id": user["id"]}


def require_permission(permission: str) -> Callable:
    """Dependency factory gating a route on ``permission`` (see ``taxflow.rbac``).

    Runs ``get_current_client`` first (so the usual 401s still apply), then
    403s if the caller's role doesn't hold ``permission``. A role missing
    from the client dict defaults to "owner" - this only happens for a
    request served mid-rollout, before every ``get_current_client`` caller is
    guaranteed to carry a real role, and erring toward the existing owner's
    full access is safer than a false 403 on legitimate traffic.
    """

    async def _dependency(client: dict = Depends(get_current_client)) -> dict:
        if not has_permission(client.get("role", "owner"), permission):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return client

    return _dependency
