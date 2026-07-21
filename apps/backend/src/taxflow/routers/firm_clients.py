import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from taxflow.db import get_db
from taxflow.middleware.auth import get_current_client

router = APIRouter(prefix="/firm-clients", tags=["firm-clients"])


class FirmClientCreate(BaseModel):
    name: str


@router.get("")
async def list_firm_clients(
    search: str | None = None, client=Depends(get_current_client), db=Depends(get_db)
):
    """Autocomplete source for the "Client (optional)" field - rows are
    upserted organically (see query.py/documents.py) the first time a name is
    used, not pre-seeded here."""
    return await asyncio.to_thread(db.firm_clients.list_for_client, client["id"], search)


@router.get("/directory")
async def list_client_directory(client=Depends(get_current_client), db=Depends(get_db)):
    """Real client directory (Nisho's #5 recommendation): every registered
    client with how many questions/documents are on file and when they were
    last touched, so a firm with hundreds of clients has an actual list to
    browse instead of only the sidebar's "highlight by client" text filter."""
    return await asyncio.to_thread(db.firm_clients.list_directory, client["id"])


@router.post("", status_code=201)
async def create_firm_client(
    body: FirmClientCreate, client=Depends(get_current_client), db=Depends(get_db)
):
    """Get-or-create an end-client by name, returning its real
    ``firm_clients.id`` (the engagement picker needs the id whether the name is
    brand-new or already exists). Scoped to the caller's ``client_id``."""
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    return await asyncio.to_thread(db.firm_clients.create, client["id"], name)
