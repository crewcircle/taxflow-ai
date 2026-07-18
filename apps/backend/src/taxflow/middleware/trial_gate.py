import asyncio
from datetime import datetime, timezone

from fastapi import Depends, HTTPException

from taxflow.middleware.auth import get_current_client
from taxflow.providers import get_relational_data


async def check_trial_gate(client: dict = Depends(get_current_client)) -> dict:
    if client.get("subscription_status") == "active":
        return client

    repos = get_relational_data()
    trial = await asyncio.to_thread(repos.trials.latest_for_client, client["id"])
    if not trial:
        raise HTTPException(
            status_code=402,
            detail={"error": "TRIAL_EXPIRED", "upgrade_url": "https://taxflow.crewcircle.com.au/upgrade"},
        )

    # psycopg2 returns timestamptz columns as aware datetimes; tolerate a string
    # too (e.g. a mocked repo) for robustness.
    ends_at = trial["trial_ends_at"]
    trial_ends_at = ends_at if isinstance(ends_at, datetime) else datetime.fromisoformat(ends_at)
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
    repos = get_relational_data()
    await asyncio.to_thread(repos.trials.increment_usage, client_id, metric)
