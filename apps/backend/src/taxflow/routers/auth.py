import os
import time

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
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

DEMO_EMAIL = "demo@taxflow.crewcircle.com.au"
_demo_login_hits: dict[str, list[float]] = {}
DEMO_LOGIN_WINDOW_SECONDS = 60
DEMO_LOGIN_MAX_PER_WINDOW = 5


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
    if client.get("is_demo"):
        raise HTTPException(status_code=403, detail="Billing is disabled for the demo account")

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


@router.post("/demo-login")
async def demo_login(request: Request):
    """Log a visitor straight into the shared demo account - no email, no signup.
    Server-side generates and immediately verifies a Supabase magic link and
    hands back the resulting session tokens directly."""
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    hits = [t for t in _demo_login_hits.get(ip, []) if now - t < DEMO_LOGIN_WINDOW_SECONDS]
    if len(hits) >= DEMO_LOGIN_MAX_PER_WINDOW:
        raise HTTPException(status_code=429, detail="Too many demo login attempts - try again shortly")
    hits.append(now)
    _demo_login_hits[ip] = hits

    sb = get_supabase_client()
    client_row = sb.table("clients").select("id").eq("email", DEMO_EMAIL).eq("is_demo", True).execute()
    if not client_row.data:
        raise HTTPException(status_code=503, detail="Demo account not configured")

    try:
        link = sb.auth.admin.generate_link(params={"type": "magiclink", "email": DEMO_EMAIL})
        anon = create_supabase_anon_client()
        session = anon.auth.verify_otp({"type": "magiclink", "token_hash": link.properties.hashed_token})
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Demo login failed: {e}") from e

    return {
        "access_token": session.session.access_token,
        "refresh_token": session.session.refresh_token,
    }


def create_supabase_anon_client():
    from supabase import create_client

    return create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)
