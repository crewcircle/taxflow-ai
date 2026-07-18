"""Tests for the Supabase AuthPort adapter (Task B5)."""

from unittest.mock import MagicMock, patch

import pytest

from taxflow.adapters.auth.supabase import AuthApiError, SupabaseAuthAdapter
from taxflow.ports.auth import AuthError, DemoSession, Identity


@patch("taxflow.adapters.auth.supabase.get_supabase_client")
def test_validate_token_returns_identity(mock_get_sb):
    sb = MagicMock()
    mock_get_sb.return_value = sb
    sb.auth.get_user.return_value.user.email = "user@example.com.au"

    identity = SupabaseAuthAdapter().validate_token("good-token")

    assert isinstance(identity, Identity)
    assert identity.email == "user@example.com.au"
    sb.auth.get_user.assert_called_once_with("good-token")


@patch("taxflow.adapters.auth.supabase.get_supabase_client")
def test_validate_token_maps_auth_api_error(mock_get_sb):
    sb = MagicMock()
    mock_get_sb.return_value = sb
    # AuthApiError signature varies by version; construct defensively.
    try:
        err = AuthApiError("bad token", 401, "invalid")
    except TypeError:
        err = AuthApiError("bad token")
    sb.auth.get_user.side_effect = err

    with pytest.raises(AuthError):
        SupabaseAuthAdapter().validate_token("bad-token")


@patch("taxflow.adapters.auth.supabase.SupabaseAuthAdapter._create_anon_client")
@patch("taxflow.adapters.auth.supabase.get_supabase_client")
def test_issue_demo_session_returns_tokens(mock_get_sb, mock_anon):
    sb = MagicMock()
    mock_get_sb.return_value = sb
    sb.auth.admin.generate_link.return_value.properties.hashed_token = "hash-123"

    anon = MagicMock()
    mock_anon.return_value = anon
    session = anon.auth.verify_otp.return_value
    session.session.access_token = "access-abc"
    session.session.refresh_token = "refresh-xyz"

    result = SupabaseAuthAdapter().issue_demo_session("demo@example.com.au")

    assert isinstance(result, DemoSession)
    assert result.access_token == "access-abc"
    assert result.refresh_token == "refresh-xyz"
    sb.auth.admin.generate_link.assert_called_once_with(
        params={"type": "magiclink", "email": "demo@example.com.au"}
    )
    anon.auth.verify_otp.assert_called_once_with(
        {"type": "magiclink", "token_hash": "hash-123"}
    )
