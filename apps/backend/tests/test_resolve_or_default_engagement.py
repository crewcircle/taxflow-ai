"""Phase 2: resolve_or_default_engagement (routers/_shared.py).

Direct unit tests against a MagicMock db, independent of any router, since
this is the one piece of new logic every insert path (query/documents/
ato_response) now depends on for attribution.
"""
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from taxflow.routers._shared import (
    LIVE_UNATTRIBUTED_DESCRIPTION,
    UNATTRIBUTED_FIRM_CLIENT_NAME,
    resolve_or_default_engagement,
)


@pytest.mark.asyncio
async def test_given_engagement_id_returns_it_with_firm_client_id():
    db = MagicMock()
    db.engagements.get_for_client.return_value = {"id": "eng-1", "firm_client_id": "fc-1"}

    result = await resolve_or_default_engagement(db, "client-1", "eng-1")

    assert result == {"engagement_id": "eng-1", "firm_client_id": "fc-1"}
    db.engagements.get_for_client.assert_called_once_with("client-1", "eng-1")
    db.firm_clients.create.assert_not_called()


@pytest.mark.asyncio
async def test_given_foreign_engagement_id_404s():
    db = MagicMock()
    db.engagements.get_for_client.return_value = None

    with pytest.raises(HTTPException) as exc:
        await resolve_or_default_engagement(db, "client-1", "foreign-eng")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_omitted_creates_unattributed_bucket_and_general_engagement():
    db = MagicMock()
    db.firm_clients.create.return_value = {"id": "fc-unattr", "name": UNATTRIBUTED_FIRM_CLIENT_NAME}
    db.engagements.get_by_firm_client_and_description.return_value = None
    db.engagements.create.return_value = {"id": "eng-general", "description": LIVE_UNATTRIBUTED_DESCRIPTION}

    result = await resolve_or_default_engagement(db, "client-1", None)

    assert result == {"engagement_id": "eng-general", "firm_client_id": "fc-unattr"}
    db.firm_clients.create.assert_called_once_with("client-1", UNATTRIBUTED_FIRM_CLIENT_NAME)
    db.engagements.get_by_firm_client_and_description.assert_called_once_with(
        "client-1", "fc-unattr", LIVE_UNATTRIBUTED_DESCRIPTION
    )
    db.engagements.create.assert_called_once_with(
        "client-1", "fc-unattr", LIVE_UNATTRIBUTED_DESCRIPTION
    )


@pytest.mark.asyncio
async def test_omitted_reuses_existing_general_engagement_without_creating_a_new_one():
    """The get-or-create must not mint a second "General" engagement (and burn
    a sequence number) once one already exists under the Unattributed bucket."""
    db = MagicMock()
    db.firm_clients.create.return_value = {"id": "fc-unattr", "name": UNATTRIBUTED_FIRM_CLIENT_NAME}
    db.engagements.get_by_firm_client_and_description.return_value = {
        "id": "eng-existing",
        "description": LIVE_UNATTRIBUTED_DESCRIPTION,
    }

    result = await resolve_or_default_engagement(db, "client-1", None)

    assert result == {"engagement_id": "eng-existing", "firm_client_id": "fc-unattr"}
    db.engagements.create.assert_not_called()


@pytest.mark.asyncio
async def test_blank_engagement_id_treated_as_omitted():
    """An empty-string engagement_id (falsy) takes the default-bucket path,
    not the ownership-lookup path."""
    db = MagicMock()
    db.firm_clients.create.return_value = {"id": "fc-unattr"}
    db.engagements.get_by_firm_client_and_description.return_value = {"id": "eng-existing"}

    result = await resolve_or_default_engagement(db, "client-1", "")

    assert result == {"engagement_id": "eng-existing", "firm_client_id": "fc-unattr"}
    db.engagements.get_for_client.assert_not_called()
