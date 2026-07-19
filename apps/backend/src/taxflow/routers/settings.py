import asyncio

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from taxflow.db import get_db
from taxflow.middleware.auth import get_current_client

router = APIRouter(prefix="/settings", tags=["settings"])

# Starting point, not a closed enum - firms can add their own via the free-text
# role field in the Staff card (e.g. "Tax Agent"). Matches AU public-practice
# title conventions.
DEFAULT_STAFF_ROLES = [
    "Principal/Director",
    "Senior Accountant",
    "Accountant",
    "Graduate/Associate",
    "Bookkeeper",
]


@router.get("/me")
async def get_me(client=Depends(get_current_client), db=Depends(get_db)):
    trial = await asyncio.to_thread(db.trials.latest_for_client, client["id"])
    return {"client": client, "trial": trial}


@router.get("/staff-roles")
async def get_staff_roles():
    return DEFAULT_STAFF_ROLES


class StaffMember(BaseModel):
    name: str
    role: str


class UpdateSettingsRequest(BaseModel):
    business_name: str | None = None
    voice_sample: str | None = None
    phone: str | None = None
    staff_directory: list[StaffMember] | None = None


@router.patch("/me")
async def update_me(body: UpdateSettingsRequest, client=Depends(get_current_client), db=Depends(get_db)):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        return client

    result = await asyncio.to_thread(db.clients.update, client["id"], updates)
    return result
