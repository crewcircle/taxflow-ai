import stripe
from fastapi import APIRouter, Depends, HTTPException, Request

from taxflow.config import settings
from taxflow.db import get_db

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/stripe")
async def stripe_webhook(request: Request, db=Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid webhook signature: {e}") from e

    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "checkout.session.completed":
        client_id = data.get("metadata", {}).get("client_id")
        if client_id:
            db.table("clients").update(
                {
                    "subscription_status": "active",
                    "stripe_customer_id": data.get("customer"),
                    "stripe_subscription_id": data.get("subscription"),
                }
            ).eq("id", client_id).execute()

    elif event_type == "customer.subscription.updated":
        db.table("clients").update({"subscription_status": data.get("status")}).eq(
            "stripe_subscription_id", data.get("id")
        ).execute()

    elif event_type == "customer.subscription.deleted":
        db.table("clients").update({"subscription_status": "cancelled"}).eq(
            "stripe_subscription_id", data.get("id")
        ).execute()

    elif event_type == "invoice.payment_failed":
        db.table("clients").update({"subscription_status": "past_due"}).eq(
            "stripe_customer_id", data.get("customer")
        ).execute()

    return {"status": "received"}
