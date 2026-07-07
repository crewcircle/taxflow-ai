from datetime import datetime, timezone

from fastapi import Depends, HTTPException

from taxflow.db import get_supabase_client
from taxflow.middleware.auth import get_current_client


async def check_trial_gate(client: dict = Depends(get_current_client)) -> dict:
    if client.get("subscription_status") == "active":
        return client

    sb = get_supabase_client()
    trial_result = (
        sb.table("trials")
        .select("*")
        .eq("client_id", client["id"])
        .order("trial_started_at", desc=True)
        .limit(1)
        .execute()
    )
    if not trial_result.data:
        raise HTTPException(
            status_code=402,
            detail={"error": "TRIAL_EXPIRED", "upgrade_url": "https://taxflow.crewcircle.com.au/upgrade"},
        )

    trial = trial_result.data[0]
    trial_ends_at = datetime.fromisoformat(trial["trial_ends_at"])
    if trial["trial_status"] == "expired" or trial_ends_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=402,
            detail={"error": "TRIAL_EXPIRED", "upgrade_url": "https://taxflow.crewcircle.com.au/upgrade"},
        )

    if trial["queries_used"] >= trial["queries_cap"]:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "TRIAL_CAP_REACHED",
                "metric": "queries",
                "used": trial["queries_used"],
                "cap": trial["queries_cap"],
            },
        )

    return client


async def increment_usage(client_id: str, metric: str) -> None:
    sb = get_supabase_client()
    sb.rpc("increment_trial_usage", {"p_client_id": client_id, "p_metric": metric}).execute()
