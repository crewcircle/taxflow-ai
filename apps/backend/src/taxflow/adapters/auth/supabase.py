"""Supabase-Auth adapter implementing
:class:`taxflow.ports.auth.AuthPort` (Task B5).

Wraps the Supabase Auth calls that ``middleware/auth.py`` and
``routers/auth.py`` used directly before: ``sb.auth.get_user(token)`` for token
validation and ``sb.auth.admin.generate_link(magiclink)`` + an anon-client
``verify_otp`` for minting demo sessions. Vendor ``AuthApiError``s are mapped to
the port's :class:`~taxflow.ports.auth.AuthError` so business/middleware code
never imports a Supabase-specific exception. The service-role client comes from
:func:`taxflow.db.get_supabase_client`.
"""

from __future__ import annotations

from taxflow.config import settings
from taxflow.db import get_supabase_client
from taxflow.ports.auth import AuthError, DemoSession, Identity

# The Supabase auth error type lives in the vendored ``supabase_auth`` package
# (historically ``gotrue``). Import defensively so a package rename doesn't break
# the adapter; fall back to ``Exception`` if it can't be located.
try:  # pragma: no cover - import shim
    from supabase_auth.errors import AuthApiError
except Exception:  # pragma: no cover - import shim
    try:
        from gotrue.errors import AuthApiError
    except Exception:
        try:
            from supabase import AuthApiError  # type: ignore[attr-defined]
        except Exception:
            AuthApiError = Exception  # type: ignore[assignment,misc]


class SupabaseAuthAdapter:
    """AuthPort adapter backed by Supabase Auth."""

    def validate_token(self, token: str) -> Identity:
        """Validate a bearer token via ``sb.auth.get_user`` and return the identity.

        Maps Supabase ``AuthApiError`` to the port's ``AuthError``.
        """
        sb = get_supabase_client()
        try:
            user_response = sb.auth.get_user(token)
        except AuthApiError as e:
            raise AuthError(str(e)) from e

        return Identity(
            email=user_response.user.email,
            sub=user_response.user.id,
            metadata=user_response.user.user_metadata or {},
        )

    def issue_demo_session(self, email: str) -> DemoSession:
        """Mint a demo session for ``email``.

        Generates a Supabase magic link with the admin (service-role) client and
        immediately verifies it with an anon client, exactly as the old
        ``demo_login`` did, returning the resulting access/refresh tokens.
        """
        sb = get_supabase_client()
        link = sb.auth.admin.generate_link(params={"type": "magiclink", "email": email})
        anon = self._create_anon_client()
        session = anon.auth.verify_otp(
            {"type": "magiclink", "token_hash": link.properties.hashed_token}
        )
        return DemoSession(
            access_token=session.session.access_token,
            refresh_token=session.session.refresh_token,
        )

    def invite_user(self, email: str) -> Identity:
        """Invite ``email`` via Supabase Auth's admin invite flow.

        Sends the vendor's own invite email (accept link) and returns the
        newly-created auth user's identity so the caller can create the
        matching ``users`` row immediately, before the invitee ever logs in.
        """
        sb = get_supabase_client()
        try:
            response = sb.auth.admin.invite_user_by_email(email)
        except AuthApiError as e:
            raise AuthError(str(e)) from e
        return Identity(email=response.user.email, sub=response.user.id, metadata={})

    @staticmethod
    def _create_anon_client():
        from supabase import create_client

        return create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)
