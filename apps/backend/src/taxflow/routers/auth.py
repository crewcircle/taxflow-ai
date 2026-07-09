import os

import stripe
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from taxflow.config import settings
from taxflow.db import get_supabase_client
from taxflow.middleware.auth import get_current_client

router = APIRouter(prefix="/auth", tags=["auth"])

TIER_PRICE_ENV = {
    "starter": "STRIPE_STARTER_PRICE_ID",
    "professional": "STRIPE_PROFESSIONAL_PRICE_ID",
    "practice": "STRIPE_PRACTICE_PRICE_ID",
}


class SignupRequest(BaseModel):
    business_name: str
    email: EmailStr
    business_type: str
    suburb: str
    state: str


@router.post("/signup")
async def signup(body: SignupRequest):
    sb = get_supabase_client()

    existing = sb.table("clients").select("id").eq("email", body.email).execute()
    if existing.data:
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    result = sb.table("clients").insert(body.model_dump()).execute()
    client_id = result.data[0]["id"]

    sb.table("trials").insert({"client_id": client_id}).execute()
    return {"client_id": client_id, "status": "trial_started"}


@router.post("/stripe-callback")
async def stripe_callback():
    # Actual session verification happens in webhooks.py via the Stripe webhook.
    return {"status": "ok"}


class CheckoutRequest(BaseModel):
    tier: str = "professional"


@router.post("/checkout-session")
async def create_checkout_session(body: CheckoutRequest, client=Depends(get_current_client)):
    """Create a Stripe Checkout session for trial-to-paid conversion.
    The checkout.session.completed webhook flips subscription_status to active."""
    env_name = TIER_PRICE_ENV.get(body.tier)
    price_id = os.environ.get(env_name, "") if env_name else ""
    if not price_id:
        raise HTTPException(status_code=400, detail=f"No price configured for tier '{body.tier}'")

    stripe.api_key = settings.STRIPE_SECRET_KEY
    session = stripe.checkout.Session.create(
        payment_method_types=["card", "au_becs_debit"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url="https://taxflow.crewcircle.com.au/dashboard?converted=true",
        cancel_url="https://taxflow.crewcircle.com.au/pricing",
        customer_email=client["email"],
        metadata={"client_id": client["id"]},
        tax_id_collection={"enabled": True},
    )
    return {"checkout_url": session["url"], "session_id": session["id"]}
