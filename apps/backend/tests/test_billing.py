"""Tests for the Stripe BillingPort adapter + router wiring (Task B6).

``stripe`` is patched so no real API calls are made. We assert the checkout
session passes the AU BECS debit payment method and tax-id collection, that
``verify_and_parse_webhook`` maps a Stripe ``SignatureVerificationError`` to the
port's ``WebhookVerificationError`` (never processing an unverified event), and
that each event type normalises into the right ``WebhookEvent`` fields. A
router-level test posts a bad signature to ``/webhooks/stripe`` and asserts a
400 with no clients-repo method invoked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import stripe

from taxflow import providers
from taxflow.adapters.billing.stripe import StripeBillingAdapter
from taxflow.ports.billing import BillingPort, CheckoutSession, WebhookEvent, WebhookVerificationError


# --- provider wiring ---------------------------------------------------------
def test_provider_resolves_default_adapter():
    providers.reset_providers()
    port = providers.get_billing_port()
    assert isinstance(port, StripeBillingAdapter)
    assert isinstance(port, BillingPort)


# --- create_checkout_session -------------------------------------------------
@patch("taxflow.adapters.billing.stripe.stripe")
def test_create_checkout_session_passes_au_becs_and_tax_id(mock_stripe, monkeypatch):
    monkeypatch.setenv("STRIPE_PROFESSIONAL_PRICE_ID", "price_pro_123")
    mock_stripe.checkout.Session.create.return_value = {
        "url": "https://checkout.stripe.com/pay/cs_test",
        "id": "cs_test_123",
    }

    result = StripeBillingAdapter().create_checkout_session(
        tier="professional",
        customer_email="firm@example.com.au",
        client_id="client-123",
    )

    assert isinstance(result, CheckoutSession)
    assert result.url == "https://checkout.stripe.com/pay/cs_test"
    assert result.id == "cs_test_123"

    _, kwargs = mock_stripe.checkout.Session.create.call_args
    assert kwargs["payment_method_types"] == ["card", "au_becs_debit"]
    assert kwargs["tax_id_collection"] == {"enabled": True}
    assert kwargs["mode"] == "subscription"
    assert kwargs["line_items"] == [{"price": "price_pro_123", "quantity": 1}]
    assert kwargs["customer_email"] == "firm@example.com.au"
    assert kwargs["metadata"] == {"client_id": "client-123"}
    assert kwargs["success_url"] == "https://taxflow.crewcircle.com.au/dashboard?converted=true"
    assert kwargs["cancel_url"] == "https://taxflow.crewcircle.com.au/pricing"


@patch("taxflow.adapters.billing.stripe.stripe")
def test_create_checkout_session_unknown_tier_raises(mock_stripe, monkeypatch):
    monkeypatch.delenv("STRIPE_PROFESSIONAL_PRICE_ID", raising=False)
    with pytest.raises(ValueError):
        StripeBillingAdapter().create_checkout_session(
            tier="does-not-exist",
            customer_email="firm@example.com.au",
            client_id="client-123",
        )
    mock_stripe.checkout.Session.create.assert_not_called()


# --- verify_and_parse_webhook: signature verification ------------------------
@patch("taxflow.adapters.billing.stripe.stripe")
def test_verify_maps_signature_error_to_port_error(mock_stripe):
    # Keep the real exception class so ``except`` matches; only the call raises.
    mock_stripe.error.SignatureVerificationError = stripe.error.SignatureVerificationError
    mock_stripe.Webhook.construct_event.side_effect = (
        stripe.error.SignatureVerificationError("bad sig", "sig_header")
    )

    with pytest.raises(WebhookVerificationError):
        StripeBillingAdapter().verify_and_parse_webhook(
            payload=b"{}", sig_header="t=1,v1=deadbeef"
        )


@patch("taxflow.adapters.billing.stripe.stripe")
def test_verify_maps_value_error_to_port_error(mock_stripe):
    mock_stripe.error.SignatureVerificationError = stripe.error.SignatureVerificationError
    mock_stripe.Webhook.construct_event.side_effect = ValueError("malformed payload")

    with pytest.raises(WebhookVerificationError):
        StripeBillingAdapter().verify_and_parse_webhook(payload=b"not-json", sig_header="")


# --- verify_and_parse_webhook: event normalisation ---------------------------
def _patch_construct_event(mock_stripe, event: dict):
    mock_stripe.error.SignatureVerificationError = stripe.error.SignatureVerificationError
    mock_stripe.Webhook.construct_event.return_value = event


@patch("taxflow.adapters.billing.stripe.stripe")
def test_verify_normalises_checkout_session_completed(mock_stripe):
    _patch_construct_event(
        mock_stripe,
        {
            "id": "evt_1",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "metadata": {"client_id": "client-abc"},
                    "customer": "cus_1",
                    "subscription": "sub_1",
                }
            },
        },
    )

    event = StripeBillingAdapter().verify_and_parse_webhook(payload=b"{}", sig_header="sig")

    assert isinstance(event, WebhookEvent)
    assert event.type == "checkout.session.completed"
    assert event.client_id == "client-abc"
    assert event.customer_id == "cus_1"
    assert event.subscription_id == "sub_1"
    assert event.id == "evt_1"


@patch("taxflow.adapters.billing.stripe.stripe")
def test_verify_normalises_subscription_updated(mock_stripe):
    _patch_construct_event(
        mock_stripe,
        {
            "id": "evt_2",
            "type": "customer.subscription.updated",
            "data": {"object": {"id": "sub_2", "status": "active", "customer": "cus_2"}},
        },
    )

    event = StripeBillingAdapter().verify_and_parse_webhook(payload=b"{}", sig_header="sig")

    assert event.type == "customer.subscription.updated"
    assert event.subscription_id == "sub_2"
    assert event.status == "active"


@patch("taxflow.adapters.billing.stripe.stripe")
def test_verify_normalises_subscription_deleted(mock_stripe):
    _patch_construct_event(
        mock_stripe,
        {
            "id": "evt_3",
            "type": "customer.subscription.deleted",
            "data": {"object": {"id": "sub_3", "status": "canceled", "customer": "cus_3"}},
        },
    )

    event = StripeBillingAdapter().verify_and_parse_webhook(payload=b"{}", sig_header="sig")

    assert event.type == "customer.subscription.deleted"
    assert event.subscription_id == "sub_3"


@patch("taxflow.adapters.billing.stripe.stripe")
def test_verify_normalises_invoice_payment_failed(mock_stripe):
    _patch_construct_event(
        mock_stripe,
        {
            "id": "evt_4",
            "type": "invoice.payment_failed",
            "data": {"object": {"customer": "cus_4", "subscription": "sub_4"}},
        },
    )

    event = StripeBillingAdapter().verify_and_parse_webhook(payload=b"{}", sig_header="sig")

    assert event.type == "invoice.payment_failed"
    assert event.customer_id == "cus_4"


# --- router: checkout endpoint delegates to the port -------------------------
@patch("taxflow.routers.auth.providers.get_billing_port")
def test_checkout_endpoint_delegates_to_billing_port(mock_get_billing, client, monkeypatch):
    from taxflow.middleware.auth import get_current_client
    from taxflow.main import app

    monkeypatch.setenv("STRIPE_PROFESSIONAL_PRICE_ID", "price_pro_123")
    billing = MagicMock()
    mock_get_billing.return_value = billing
    billing.create_checkout_session.return_value = CheckoutSession(
        url="https://checkout.stripe.com/pay/cs_test", id="cs_test_123"
    )

    app.dependency_overrides[get_current_client] = lambda: {
        "id": "client-123",
        "email": "firm@example.com.au",
    }
    try:
        response = client.post("/auth/checkout-session", json={"tier": "professional"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["checkout_url"] == "https://checkout.stripe.com/pay/cs_test"
    assert body["session_id"] == "cs_test_123"
    billing.create_checkout_session.assert_called_once_with(
        tier="professional",
        customer_email="firm@example.com.au",
        client_id="client-123",
    )


@patch("taxflow.routers.auth.providers.get_billing_port")
def test_checkout_endpoint_demo_account_forbidden(mock_get_billing, client):
    from taxflow.middleware.auth import get_current_client
    from taxflow.main import app

    billing = MagicMock()
    mock_get_billing.return_value = billing

    app.dependency_overrides[get_current_client] = lambda: {
        "id": "client-demo",
        "email": "demo@example.com.au",
        "is_demo": True,
    }
    try:
        response = client.post("/auth/checkout-session", json={"tier": "professional"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    billing.create_checkout_session.assert_not_called()


@patch("taxflow.routers.auth.providers.get_billing_port")
def test_checkout_endpoint_unknown_tier_400(mock_get_billing, client, monkeypatch):
    from taxflow.middleware.auth import get_current_client
    from taxflow.main import app

    monkeypatch.delenv("STRIPE_STARTER_PRICE_ID", raising=False)
    billing = MagicMock()
    mock_get_billing.return_value = billing

    app.dependency_overrides[get_current_client] = lambda: {
        "id": "client-123",
        "email": "firm@example.com.au",
    }
    try:
        response = client.post("/auth/checkout-session", json={"tier": "starter"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    billing.create_checkout_session.assert_not_called()


# --- router: webhook endpoint dispatch + bad-signature guard -----------------
def _override_db(mock_db):
    from taxflow.db import get_db
    from taxflow.main import app

    app.dependency_overrides[get_db] = lambda: mock_db


@patch("taxflow.routers.webhooks.providers.get_billing_port")
def test_webhook_bad_signature_returns_400_and_no_repo_call(mock_get_billing, client):
    from taxflow.main import app

    billing = MagicMock()
    mock_get_billing.return_value = billing
    billing.verify_and_parse_webhook.side_effect = WebhookVerificationError("bad sig")

    mock_db = MagicMock()
    _override_db(mock_db)
    try:
        response = client.post(
            "/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "t=1,v1=deadbeef"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    mock_db.clients.activate_from_checkout.assert_not_called()
    mock_db.clients.set_subscription_by_stripe_subscription_id.assert_not_called()
    mock_db.clients.set_subscription_by_customer_id.assert_not_called()


@patch("taxflow.routers.webhooks.providers.get_billing_port")
def test_webhook_checkout_completed_activates_client(mock_get_billing, client):
    from taxflow.main import app

    billing = MagicMock()
    mock_get_billing.return_value = billing
    billing.verify_and_parse_webhook.return_value = WebhookEvent(
        type="checkout.session.completed",
        client_id="client-abc",
        customer_id="cus_1",
        subscription_id="sub_1",
        id="evt_1",
    )

    mock_db = MagicMock()
    _override_db(mock_db)
    try:
        response = client.post(
            "/webhooks/stripe", content=b"{}", headers={"stripe-signature": "sig"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    mock_db.clients.activate_from_checkout.assert_called_once_with(
        "client-abc",
        {
            "subscription_status": "active",
            "stripe_customer_id": "cus_1",
            "stripe_subscription_id": "sub_1",
        },
    )


@patch("taxflow.routers.webhooks.providers.get_billing_port")
def test_webhook_subscription_updated_sets_status(mock_get_billing, client):
    from taxflow.main import app

    billing = MagicMock()
    mock_get_billing.return_value = billing
    billing.verify_and_parse_webhook.return_value = WebhookEvent(
        type="customer.subscription.updated",
        subscription_id="sub_2",
        status="active",
    )

    mock_db = MagicMock()
    _override_db(mock_db)
    try:
        response = client.post(
            "/webhooks/stripe", content=b"{}", headers={"stripe-signature": "sig"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    mock_db.clients.set_subscription_by_stripe_subscription_id.assert_called_once_with(
        "sub_2", {"subscription_status": "active"}
    )


@patch("taxflow.routers.webhooks.providers.get_billing_port")
def test_webhook_subscription_deleted_cancels(mock_get_billing, client):
    from taxflow.main import app

    billing = MagicMock()
    mock_get_billing.return_value = billing
    billing.verify_and_parse_webhook.return_value = WebhookEvent(
        type="customer.subscription.deleted",
        subscription_id="sub_3",
    )

    mock_db = MagicMock()
    _override_db(mock_db)
    try:
        response = client.post(
            "/webhooks/stripe", content=b"{}", headers={"stripe-signature": "sig"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    mock_db.clients.set_subscription_by_stripe_subscription_id.assert_called_once_with(
        "sub_3", {"subscription_status": "cancelled"}
    )


@patch("taxflow.routers.webhooks.providers.get_billing_port")
def test_webhook_invoice_payment_failed_sets_past_due(mock_get_billing, client):
    from taxflow.main import app

    billing = MagicMock()
    mock_get_billing.return_value = billing
    billing.verify_and_parse_webhook.return_value = WebhookEvent(
        type="invoice.payment_failed",
        customer_id="cus_4",
    )

    mock_db = MagicMock()
    _override_db(mock_db)
    try:
        response = client.post(
            "/webhooks/stripe", content=b"{}", headers={"stripe-signature": "sig"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    mock_db.clients.set_subscription_by_customer_id.assert_called_once_with(
        "cus_4", {"subscription_status": "past_due"}
    )
