import asyncio

from fastapi import HTTPException, Request

from taxflow import providers
from taxflow.ports.auth import AuthError


async def get_current_client(request: Request) -> dict:
    """Validate the bearer token via the AuthPort and return the client row.

    Missing/malformed bearer → 401; invalid token (AuthError) → 401. A valid
    token with no matching client row means the user authenticated via OAuth
    (Google/Microsoft) and never went through POST /api/signup, which normally
    creates the row — so we auto-provision a minimal trial account here instead
    of 404ing, mirroring what /api/signup does for the columns it doesn't
    collect explicitly.
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
    return client


def _get_or_provision_client(identity) -> dict:
    """Return the client row for ``identity``, provisioning one if none exists."""
    clients = providers.get_relational_data().clients
    client = clients.get_by_email(identity.email)
    if client:
        return client

    metadata = identity.metadata or {}
    business_name = (
        metadata.get("full_name")
        or metadata.get("name")
        or identity.email.split("@")[0]
    )
    client = clients.create(
        {
            "business_name": business_name,
            "email": identity.email,
            "business_type": "other",
            "suburb": "",
            "state": "NSW",
        }
    )
    providers.get_relational_data().trials.create(client["id"])
    return client
