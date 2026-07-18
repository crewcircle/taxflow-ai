import asyncio

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr

from taxflow.db import get_db

router = APIRouter(prefix="/contact", tags=["contact"])


class ContactRequest(BaseModel):
    name: str
    email: EmailStr
    firm_name: str | None = None
    message: str


@router.post("")
async def submit_contact(body: ContactRequest, db=Depends(get_db)):
    await asyncio.to_thread(db.contact.insert, body.model_dump())
    return {"status": "received"}
