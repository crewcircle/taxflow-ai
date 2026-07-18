from fastapi import HTTPException, Request
from supabase_auth.errors import AuthApiError

from taxflow.db import get_supabase_client


async def get_current_client(request: Request) -> dict:
    """Validate the Supabase JWT from the Authorization header and return the client row."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = auth_header.split(" ", 1)[1]
    sb = get_supabase_client()

    try:
        user_response = sb.auth.get_user(token)
    except AuthApiError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}") from e

    email = user_response.user.email
    result = sb.table("clients").select("*").eq("email", email).execute()
    if result.data:
        return result.data[0]

    # No clients row yet: this user authenticated via OAuth (Google/Microsoft)
    # and never went through POST /api/signup, which normally creates it.
    # Auto-provision a minimal trial account here instead of 401ing, mirroring
    # what /api/signup does for the columns it doesn't collect explicitly.
    metadata = user_response.user.user_metadata or {}
    business_name = metadata.get("full_name") or metadata.get("name") or email.split("@")[0]
    client = (
        sb.table("clients")
        .insert(
            {
                "business_name": business_name,
                "email": email,
                "business_type": "other",
                "suburb": "",
                "state": "NSW",
            }
        )
        .execute()
    )
    client_row = client.data[0]
    sb.table("trials").insert({"client_id": client_row["id"]}).execute()
    return client_row
