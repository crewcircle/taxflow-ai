import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from taxflow.db import get_db
from taxflow.middleware.auth import get_current_client
from taxflow.services.document_templates import (
    SYSTEM_DEFAULTS,
    list_templates_for_client,
)

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


# --- Phase 5: firm-level editable document templates -------------------------


class UpdateTemplateRequest(BaseModel):
    body: str


@router.get("/templates")
async def list_templates(client=Depends(get_current_client)):
    """List the editable document templates with each type's resolved body (the
    firm's override if set, else the code-owned system default) and whether the
    firm has a custom row."""
    return await asyncio.to_thread(list_templates_for_client, client["id"])


@router.put("/templates/{template_key}")
async def upsert_template(
    template_key: str,
    body: UpdateTemplateRequest,
    client=Depends(get_current_client),
    db=Depends(get_db),
):
    if template_key not in SYSTEM_DEFAULTS:
        raise HTTPException(status_code=400, detail="Unknown template_key")
    if not body.body or not body.body.strip():
        raise HTTPException(status_code=400, detail="Template body must not be empty")
    return await asyncio.to_thread(
        db.document_templates.upsert,
        client["id"],
        template_key,
        body.body,
        client.get("email") or client.get("business_name"),
    )


@router.delete("/templates/{template_key}")
async def reset_template(
    template_key: str, client=Depends(get_current_client), db=Depends(get_db)
):
    """Reset a template to its system default by removing the firm's override
    row."""
    if template_key not in SYSTEM_DEFAULTS:
        raise HTTPException(status_code=400, detail="Unknown template_key")
    await asyncio.to_thread(db.document_templates.delete, client["id"], template_key)
    return {"status": "reset", "template_key": template_key}


@router.post("/templates/{template_key}/reset-to-default")
async def reset_template_to_default(
    template_key: str, client=Depends(get_current_client), db=Depends(get_db)
):
    """Alias for the DELETE reset route (authoritative Phase 5 spec names a
    POST reset-to-default action)."""
    return await reset_template(template_key, client=client, db=db)
