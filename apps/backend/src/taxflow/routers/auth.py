from fastapi import APIRouter
from pydantic import BaseModel, EmailStr

from taxflow.db import get_supabase_client

router = APIRouter(prefix="/auth", tags=["auth"])


class SignupRequest(BaseModel):
    business_name: str
    email: EmailStr
    business_type: str
    suburb: str
    state: str


@router.post("/signup")
async def signup(body: SignupRequest):
    sb = get_supabase_client()
    result = sb.table("clients").insert(body.model_dump()).execute()
    client_id = result.data[0]["id"]

    sb.table("trials").insert({"client_id": client_id}).execute()
    return {"client_id": client_id, "status": "trial_started"}


@router.post("/stripe-callback")
async def stripe_callback():
    # Actual session verification happens in webhooks.py via the Stripe webhook.
    return {"status": "ok"}
