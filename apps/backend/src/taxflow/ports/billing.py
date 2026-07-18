"""Port Protocol for billing (checkout + webhook verification)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class WebhookVerificationError(Exception):
    """Raised when a billing webhook signature cannot be verified. -> HTTP 400."""


@dataclass
class CheckoutSession:
    url: str
    id: str


@dataclass
class WebhookEvent:
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    # Normalised fields handlers need, extracted by the adapter:
    client_id: str | None = None
    customer_id: str | None = None
    subscription_id: str | None = None
    status: str | None = None
    id: str | None = None


@runtime_checkable
class BillingPort(Protocol):
    def create_checkout_session(
        self, *, tier: str, customer_email: str, client_id: str
    ) -> CheckoutSession: ...

    def verify_and_parse_webhook(self, *, payload: bytes, sig_header: str) -> WebhookEvent:
        """Verify signature and return a normalised event, or raise
        WebhookVerificationError. Signature verification must never be skipped."""
        ...
