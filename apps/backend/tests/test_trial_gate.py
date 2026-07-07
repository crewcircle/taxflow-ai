from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from taxflow.middleware.trial_gate import check_trial_gate


def _trial_row(**overrides):
    base = {
        "trial_status": "active",
        "trial_ends_at": (datetime.now(timezone.utc) + timedelta(days=10)).isoformat(),
        "queries_used": 5,
        "queries_cap": 100,
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
@patch("taxflow.middleware.trial_gate.get_supabase_client")
async def test_active_paid_subscriber_passes(mock_get_client):
    client = {"id": "c1", "subscription_status": "active"}
    result = await check_trial_gate(client=client)
    assert result == client
    mock_get_client.assert_not_called()


@pytest.mark.asyncio
@patch("taxflow.middleware.trial_gate.get_supabase_client")
async def test_expired_trial_returns_402(mock_get_client):
    mock_sb = MagicMock()
    mock_get_client.return_value = mock_sb
    mock_sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
        _trial_row(trial_status="expired")
    ]

    client = {"id": "c1", "subscription_status": "trialing"}
    with pytest.raises(HTTPException) as exc_info:
        await check_trial_gate(client=client)
    assert exc_info.value.status_code == 402
    assert exc_info.value.detail["error"] == "TRIAL_EXPIRED"


@pytest.mark.asyncio
@patch("taxflow.middleware.trial_gate.get_supabase_client")
async def test_trial_cap_reached_returns_402(mock_get_client):
    mock_sb = MagicMock()
    mock_get_client.return_value = mock_sb
    mock_sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
        _trial_row(queries_used=100, queries_cap=100)
    ]

    client = {"id": "c1", "subscription_status": "trialing"}
    with pytest.raises(HTTPException) as exc_info:
        await check_trial_gate(client=client)
    assert exc_info.value.status_code == 402
    assert exc_info.value.detail["error"] == "TRIAL_CAP_REACHED"


@pytest.mark.asyncio
@patch("taxflow.middleware.trial_gate.get_supabase_client")
async def test_active_trial_within_cap_passes(mock_get_client):
    mock_sb = MagicMock()
    mock_get_client.return_value = mock_sb
    mock_sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
        _trial_row()
    ]

    client = {"id": "c1", "subscription_status": "trialing"}
    result = await check_trial_gate(client=client)
    assert result == client
