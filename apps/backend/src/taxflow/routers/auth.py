import asyncio
import os
import random
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr

from taxflow import providers
from taxflow.middleware.auth import get_current_client

router = APIRouter(prefix="/auth", tags=["auth"])

TIER_PRICE_ENV = {
    "starter": "STRIPE_STARTER_PRICE_ID",
    "professional": "STRIPE_PROFESSIONAL_PRICE_ID",
    "practice": "STRIPE_PRACTICE_PRICE_ID",
}

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
    clients = providers.get_relational_data().clients
    trials = providers.get_relational_data().trials

    if await asyncio.to_thread(clients.email_exists, body.email):
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    created = await asyncio.to_thread(clients.create, body.model_dump())
    client_id = created["id"]

    await asyncio.to_thread(trials.create, client_id)
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

    session = providers.get_billing_port().create_checkout_session(
        tier=body.tier,
        customer_email=client["email"],
        client_id=client["id"],
    )
    return {"checkout_url": session.url, "session_id": session.id}


@router.post("/demo-login")
async def demo_login(request: Request, persona: str | None = None):
    """Log a visitor into a demo persona - no email, no signup. `persona`
    (a business_type, e.g. "dental") targets a specific one for the persona
    switcher; omitted, one is chosen at random. Server-side generates and
    immediately verifies a Supabase magic link and hands back the resulting
    session tokens directly."""
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    hits = [t for t in _demo_login_hits.get(ip, []) if now - t < DEMO_LOGIN_WINDOW_SECONDS]
    if len(hits) >= DEMO_LOGIN_MAX_PER_WINDOW:
        raise HTTPException(status_code=429, detail="Too many demo login attempts - try again shortly")
    hits.append(now)
    _demo_login_hits[ip] = hits

    demo_emails = await asyncio.to_thread(
        providers.get_relational_data().clients.find_demo_emails, persona
    )
    if not demo_emails:
        raise HTTPException(status_code=503, detail="Demo account not configured")
    demo_email = random.choice(demo_emails)

    try:
        session = providers.get_auth_port().issue_demo_session(demo_email)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Demo login failed: {e}") from e

    return {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
    }
