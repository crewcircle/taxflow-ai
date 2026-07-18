import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from taxflow import providers
from taxflow.db import get_db
from taxflow.ports.billing import WebhookVerificationError

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/stripe")
async def stripe_webhook(request: Request, db=Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = providers.get_billing_port().verify_and_parse_webhook(
            payload=payload, sig_header=sig_header
        )
    except WebhookVerificationError as e:
        raise HTTPException(status_code=400, detail=f"Invalid webhook signature: {e}") from e

    if event.type == "checkout.session.completed":
        if event.client_id:
            await asyncio.to_thread(
                db.clients.activate_from_checkout,
                event.client_id,
                {
                    "subscription_status": "active",
                    "stripe_customer_id": event.customer_id,
                    "stripe_subscription_id": event.subscription_id,
                },
            )

    elif event.type == "customer.subscription.updated":
        await asyncio.to_thread(
            db.clients.set_subscription_by_stripe_subscription_id,
            event.subscription_id,
            {"subscription_status": event.status},
        )

    elif event.type == "customer.subscription.deleted":
        await asyncio.to_thread(
            db.clients.set_subscription_by_stripe_subscription_id,
            event.subscription_id,
            {"subscription_status": "cancelled"},
        )

    elif event.type == "invoice.payment_failed":
        await asyncio.to_thread(
            db.clients.set_subscription_by_customer_id,
            event.customer_id,
            {"subscription_status": "past_due"},
        )

    return {"status": "received"}
