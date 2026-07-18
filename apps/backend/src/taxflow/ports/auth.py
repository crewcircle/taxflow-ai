"""Port Protocol for authentication (validate bearer token -> identity)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


class AuthError(Exception):
    """Raised when a token is missing/invalid. Adapters map vendor errors to this."""


@dataclass
class Identity:
    email: str
    # Provider-supplied user metadata (e.g. OAuth full_name/name). Empty when the
    # backing auth provider exposes none. Used to auto-provision a client row for
    # users who authenticated via OAuth and never went through POST /api/signup.
    metadata: dict = field(default_factory=dict)


@dataclass
class DemoSession:
    access_token: str
    refresh_token: str


@runtime_checkable
class AuthPort(Protocol):
    def validate_token(self, token: str) -> Identity:
        """Validate a bearer token and return the caller identity, or raise AuthError."""
        ...

    def issue_demo_session(self, email: str) -> DemoSession:
        """Mint a demo session (access/refresh tokens) for the given email."""
        ...
