"""Phase 3: query.py's eager query_sessions creation on the first turn of a
session. Follows test_engagements_api.py's style (MagicMock db, real router
functions called directly)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

CLIENT = {"id": "client-1", "email": "a@b.com.au", "user_id": "user-1"}


@pytest.mark.asyncio
async def test_stream_query_creates_session_row_when_session_id_present():
    import taxflow.routers.query as q

    mock_db = MagicMock()
    mock_db.engagements.get_for_client.return_value = {"id": "eng-1", "firm_client_id": "fc-1"}
    mock_db.queries.insert.return_value = {"id": "query-1"}
    mock_db.queries.update.side_effect = lambda cid, qid, payload: None

    async def fake_astream(initial_state, stream_mode=None):
        yield ("custom", {"token": "hi"})
        yield ("values", {"answer": "hi", "citations": [], "confidence": 0.5,
                          "routed_tier": "haiku", "input_tokens": 1, "output_tokens": 1,
                          "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0})

    with patch.object(q, "embed", new=AsyncMock(return_value=[0.0] * 1536)), \
         patch.object(q, "increment_usage", new=AsyncMock()), \
         patch.object(q.research_graph, "astream", new=fake_astream), \
         patch.object(q.answer_cache, "store_answer", new=AsyncMock()), \
         patch.object(q.answer_cache, "get_cached_answer", new=AsyncMock(return_value=None)), \
         patch.object(q.answer_cache, "count_prior_asks", new=AsyncMock(return_value=0)):
        response = await q.stream_query(
            question="q",
            session_id="sess-1",
            engagement_id="eng-1",
            client=CLIENT,
            _trial=CLIENT,
            db=mock_db,
        )
        _ = [c async for c in response.body_iterator]

    mock_db.query_sessions.get_or_create.assert_called_once_with(
        "client-1", "sess-1", "eng-1", "fc-1"
    )


@pytest.mark.asyncio
async def test_stream_query_skips_session_creation_without_session_id():
    import taxflow.routers.query as q

    mock_db = MagicMock()
    mock_db.engagements.get_for_client.return_value = {"id": "eng-1", "firm_client_id": "fc-1"}
    mock_db.queries.insert.return_value = {"id": "query-1"}
    mock_db.queries.update.side_effect = lambda cid, qid, payload: None

    async def fake_astream(initial_state, stream_mode=None):
        yield ("values", {"answer": "hi", "citations": [], "confidence": 0.5,
                          "routed_tier": "haiku", "input_tokens": 1, "output_tokens": 1,
                          "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0})

    with patch.object(q, "embed", new=AsyncMock(return_value=[0.0] * 1536)), \
         patch.object(q, "increment_usage", new=AsyncMock()), \
         patch.object(q.research_graph, "astream", new=fake_astream), \
         patch.object(q.answer_cache, "store_answer", new=AsyncMock()), \
         patch.object(q.answer_cache, "get_cached_answer", new=AsyncMock(return_value=None)), \
         patch.object(q.answer_cache, "count_prior_asks", new=AsyncMock(return_value=0)):
        response = await q.stream_query(
            question="q",
            client=CLIENT,
            _trial=CLIENT,
            db=mock_db,
        )
        _ = [c async for c in response.body_iterator]

    mock_db.query_sessions.get_or_create.assert_not_called()


@pytest.mark.asyncio
async def test_submit_query_creates_session_row_when_session_id_present():
    import taxflow.routers.query as q

    mock_db = MagicMock()
    mock_db.engagements.create.return_value = {"id": "eng-general"}
    mock_db.firm_clients.create.return_value = {"id": "fc-unattr"}
    mock_db.engagements.get_by_firm_client_and_description.return_value = None
    mock_db.queries.insert.return_value = {"id": "query-1"}

    async def fake_ainvoke(state):
        return {
            "answer": "hi",
            "citations": [],
            "confidence": 0.5,
            "routed_tier": "haiku",
            "input_tokens": 1,
            "output_tokens": 1,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }

    body = q.QueryRequest(question="q", session_id="sess-1")

    with patch.object(q, "embed", new=AsyncMock(return_value=[0.0] * 1536)), \
         patch.object(q, "increment_usage", new=AsyncMock()), \
         patch.object(q.research_graph, "ainvoke", new=fake_ainvoke), \
         patch.object(q.answer_cache, "get_cached_answer", new=AsyncMock(return_value=None)), \
         patch.object(q.answer_cache, "store_answer", new=AsyncMock()), \
         patch.object(q.answer_cache, "count_prior_asks", new=AsyncMock(return_value=0)):
        await q.submit_query(body=body, client=CLIENT, _trial=CLIENT, db=mock_db)

    mock_db.query_sessions.get_or_create.assert_called_once_with(
        "client-1", "sess-1", "eng-general", "fc-unattr"
    )
