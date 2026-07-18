"""Stripe adapter implementing :class:`taxflow.ports.billing.BillingPort` (Task B6).

Wraps the two Stripe calls that ``routers/auth.py`` (checkout) and
``routers/webhooks.py`` (webhook) used directly before:
``stripe.checkout.Session.create(...)`` for trial-to-paid conversion and
``stripe.Webhook.construct_event(...)`` for signature verification. The
vendor-specific ``ValueError``/``stripe.error.SignatureVerificationError`` are
mapped to the port's :class:`~taxflow.ports.billing.WebhookVerificationError` so
router/business code never handles a Stripe-specific exception, and the raw
Stripe event is normalised into a :class:`~taxflow.ports.billing.WebhookEvent`.

``stripe.Webhook.construct_event`` is the *only* place signature verification
happens and must never be skipped or bypassed.
"""

from __future__ import annotations

import os

import stripe

from taxflow.config import settings
from taxflow.ports.billing import CheckoutSession, WebhookEvent, WebhookVerificationError

# Tier -> env var holding the Stripe price id (unchanged from the old router).
TIER_PRICE_ENV = {
    "starter": "STRIPE_STARTER_PRICE_ID",
    "professional": "STRIPE_PROFESSIONAL_PRICE_ID",
    "practice": "STRIPE_PRACTICE_PRICE_ID",
}

SUCCESS_URL = "https://taxflow.crewcircle.com.au/dashboard?converted=true"
CANCEL_URL = "https://taxflow.crewcircle.com.au/pricing"


class StripeBillingAdapter:
    """BillingPort adapter backed by Stripe."""

    def create_checkout_session(
        self, *, tier: str, customer_email: str, client_id: str
    ) -> CheckoutSession:
        """Create a Stripe Checkout session for trial-to-paid conversion.

        The ``checkout.session.completed`` webhook flips subscription_status to
        active. Keeps today's exact args: card + AU BECS debit payment methods,
        subscription mode, tax-id collection enabled, the same success/cancel
        URLs, and ``client_id`` in the metadata.
        """
        env_name = TIER_PRICE_ENV.get(tier)
        price_id = os.environ.get(env_name, "") if env_name else ""
        if not price_id:
            raise ValueError(f"No price configured for tier '{tier}'")

        stripe.api_key = settings.STRIPE_SECRET_KEY
        session = stripe.checkout.Session.create(
            payment_method_types=["card", "au_becs_debit"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            success_url=SUCCESS_URL,
            cancel_url=CANCEL_URL,
            customer_email=customer_email,
            metadata={"client_id": client_id},
            tax_id_collection={"enabled": True},
        )
        return CheckoutSession(url=session["url"], id=session["id"])

    def verify_and_parse_webhook(self, *, payload: bytes, sig_header: str) -> WebhookEvent:
        """Verify the Stripe signature and normalise the event.

        ``stripe.Webhook.construct_event`` performs the signature verification;
        it is the only place that happens and must never be skipped. Vendor
        ``ValueError`` (malformed payload) and
        ``stripe.error.SignatureVerificationError`` (bad signature) are mapped to
        the port's ``WebhookVerificationError``.
        """
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )
        except (ValueError, stripe.error.SignatureVerificationError) as e:
            raise WebhookVerificationError(f"Invalid webhook signature: {e}") from e

        event_type = event["type"]
        data = event["data"]["object"]
        # A checkout.session object carries the subscription id under
        # ``subscription``; a subscription object *is* the subscription, so its
        # own ``id`` is the subscription id.
        subscription_id = data.get("subscription") or data.get("id")
        return WebhookEvent(
            type=event_type,
            data=data,
            client_id=data.get("metadata", {}).get("client_id"),
            customer_id=data.get("customer"),
            subscription_id=subscription_id,
            status=data.get("status"),
            id=event.get("id"),
        )
