from fastapi import APIRouter
from pydantic import BaseModel, EmailStr

from taxflow.db import get_supabase_client

router = APIRouter(prefix="/contact", tags=["contact"])


class ContactRequest(BaseModel):
    name: str
    email: EmailStr
    firm_name: str | None = None
    message: str


@router.post("")
async def submit_contact(body: ContactRequest):
    sb = get_supabase_client()
    sb.table("contact_messages").insert(body.model_dump()).execute()
    return {"status": "received"}
