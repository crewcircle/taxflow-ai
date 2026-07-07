from fastapi import Depends, HTTPException, Request
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
    if not result.data:
        raise HTTPException(status_code=404, detail="Client not found")

    return result.data[0]
