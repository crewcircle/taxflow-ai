import time

from fastapi import Depends, HTTPException

from taxflow.db import get_supabase_client
from taxflow.middleware.auth import get_current_client

WINDOW_SECONDS = 60
MAX_REQUESTS_PER_WINDOW = 30


async def check_rate_limit(client: dict = Depends(get_current_client)) -> dict:
    """Sliding-window rate limit per client, backed by a Supabase table."""
    sb = get_supabase_client()
    now = time.time()
    window_start = now - WINDOW_SECONDS

    sb.table("rate_limit_hits").delete().eq("client_id", client["id"]).lt("ts", window_start).execute()
    hits = sb.table("rate_limit_hits").select("id").eq("client_id", client["id"]).execute()

    if len(hits.data) >= MAX_REQUESTS_PER_WINDOW:
        raise HTTPException(status_code=429, detail="Rate limit exceeded, please slow down")

    sb.table("rate_limit_hits").insert({"client_id": client["id"], "ts": now}).execute()
    return client
