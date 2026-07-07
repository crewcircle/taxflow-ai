from functools import lru_cache

from supabase import create_client, Client

from taxflow.config import settings


@lru_cache
def get_supabase_client() -> Client:
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


async def get_db() -> Client:
    return get_supabase_client()
