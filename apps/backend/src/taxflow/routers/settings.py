from fastapi import APIRouter, Depends
from pydantic import BaseModel

from taxflow.db import get_db
from taxflow.middleware.auth import get_current_client

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/me")
async def get_me(client=Depends(get_current_client), db=Depends(get_db)):
    trial = (
        db.table("trials")
        .select("*")
        .eq("client_id", client["id"])
        .order("trial_started_at", desc=True)
        .limit(1)
        .execute()
    )
    return {"client": client, "trial": trial.data[0] if trial.data else None}


class UpdateSettingsRequest(BaseModel):
    business_name: str | None = None
    voice_sample: str | None = None
    phone: str | None = None


@router.patch("/me")
async def update_me(body: UpdateSettingsRequest, client=Depends(get_current_client), db=Depends(get_db)):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        return client

    result = db.table("clients").update(updates).eq("id", client["id"]).execute()
    return result.data[0]
