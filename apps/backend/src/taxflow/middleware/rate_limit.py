import asyncio

from fastapi import Depends, HTTPException

from taxflow.middleware.auth import get_current_client
from taxflow.providers import get_relational_data

WINDOW_SECONDS = 60
MAX_REQUESTS_PER_WINDOW = 30


async def check_rate_limit(client: dict = Depends(get_current_client)) -> dict:
    """Sliding-window rate limit per client, backed by the rate_limit repo."""
    repos = get_relational_data()

    def _check() -> int:
        repos.rate_limit.purge_older_than(WINDOW_SECONDS)
        count = repos.rate_limit.count_hits(client["id"], WINDOW_SECONDS)
        return count

    hits = await asyncio.to_thread(_check)
    if hits >= MAX_REQUESTS_PER_WINDOW:
        raise HTTPException(status_code=429, detail="Rate limit exceeded, please slow down")

    await asyncio.to_thread(repos.rate_limit.record_hit, client["id"])
    return client
