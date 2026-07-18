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


def _repos_returning(trial):
    """Build a mock RelationalDataPort facade whose trials repo returns `trial`."""
    repos = MagicMock()
    repos.trials.latest_for_client.return_value = trial
    return repos


@pytest.mark.asyncio
@patch("taxflow.middleware.trial_gate.get_relational_data")
async def test_active_paid_subscriber_passes(mock_get_repos):
    client = {"id": "c1", "subscription_status": "active"}
    result = await check_trial_gate(client=client)
    assert result == client
    mock_get_repos.assert_not_called()


@pytest.mark.asyncio
@patch("taxflow.middleware.trial_gate.get_relational_data")
async def test_expired_trial_returns_402(mock_get_repos):
    mock_get_repos.return_value = _repos_returning(_trial_row(trial_status="expired"))

    client = {"id": "c1", "subscription_status": "trialing"}
    with pytest.raises(HTTPException) as exc_info:
        await check_trial_gate(client=client)
    assert exc_info.value.status_code == 402
    assert exc_info.value.detail["error"] == "TRIAL_EXPIRED"


@pytest.mark.asyncio
@patch("taxflow.middleware.trial_gate.get_relational_data")
async def test_no_trial_returns_402(mock_get_repos):
    mock_get_repos.return_value = _repos_returning(None)

    client = {"id": "c1", "subscription_status": "trialing"}
    with pytest.raises(HTTPException) as exc_info:
        await check_trial_gate(client=client)
    assert exc_info.value.status_code == 402
    assert exc_info.value.detail["error"] == "TRIAL_EXPIRED"


@pytest.mark.asyncio
@patch("taxflow.middleware.trial_gate.get_relational_data")
async def test_trial_cap_reached_returns_402(mock_get_repos):
    mock_get_repos.return_value = _repos_returning(_trial_row(queries_used=100, queries_cap=100))

    client = {"id": "c1", "subscription_status": "trialing"}
    with pytest.raises(HTTPException) as exc_info:
        await check_trial_gate(client=client)
    assert exc_info.value.status_code == 402
    assert exc_info.value.detail["error"] == "TRIAL_CAP_REACHED"


@pytest.mark.asyncio
@patch("taxflow.middleware.trial_gate.get_relational_data")
async def test_active_trial_within_cap_passes(mock_get_repos):
    mock_get_repos.return_value = _repos_returning(_trial_row())

    client = {"id": "c1", "subscription_status": "trialing"}
    result = await check_trial_gate(client=client)
    assert result == client
    mock_get_repos.return_value.trials.latest_for_client.assert_called_once_with("c1")
