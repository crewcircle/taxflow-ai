import asyncio

from fastapi import APIRouter, Depends

from taxflow.db import get_db
from taxflow.middleware.auth import get_current_client

router = APIRouter(prefix="/firm-clients", tags=["firm-clients"])


@router.get("")
async def list_firm_clients(
    search: str | None = None, client=Depends(get_current_client), db=Depends(get_db)
):
    """Autocomplete source for the "Client (optional)" field - rows are
    upserted organically (see query.py/documents.py) the first time a name is
    used, not pre-seeded here."""
    return await asyncio.to_thread(db.firm_clients.list_for_client, client["id"], search)
