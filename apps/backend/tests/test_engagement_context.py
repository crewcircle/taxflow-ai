"""Task C4: engagement context store — embed-on-save + scoped retrieval.

Covers:
  - generate_document embeds + inserts an engagement_context row for an approved
    client-facing document type (mock embed);
  - an embed failure never blocks the document save;
  - engagement_search filters by client_id AND client_ref;
  - _retrieve_context merges engagement hits when client_ref is present and
    skips the engagement search entirely when it is absent.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# --- generate_document: embed-on-save ----------------------------------------


def _override(fake_client, mock_db):
    from taxflow.main import app
    from taxflow.db import get_db
    from taxflow.middleware.auth import get_current_client

    app.dependency_overrides[get_current_client] = lambda: fake_client
    app.dependency_overrides[get_db] = lambda: mock_db


def _mock_db():
    mock_db = MagicMock()
    mock_db.documents.insert.return_value = {"id": "doc-1", "title": "Memo"}
    return mock_db


def test_generate_document_inserts_engagement_context_with_embedding(client):
    from taxflow.main import app
    from taxflow.routers import documents as documents_router

    fake_client = {"id": "client-1", "email": "a@b.com.au", "business_name": "Acme"}
    mock_db = _mock_db()
    _override(fake_client, mock_db)

    fake_state = {"result_md": "# Advice\n\nBody text."}
    embedding = [0.1] * 1536

    try:
        with patch.object(
            documents_router.document_graph, "ainvoke", new=AsyncMock(return_value=fake_state)
        ), patch.object(
            documents_router, "embed", new=AsyncMock(return_value=embedding)
        ) as mock_embed:
            resp = client.post(
                "/documents/generate",
                json={
                    "document_type": "advice_memo",
                    "title": "Memo",
                    "content_md": "raw",
                    "client_ref": "Client A",
                },
            )
        assert resp.status_code == 200

        # The reformatted content was embedded and stored in engagement_context.
        mock_embed.assert_awaited_once_with("# Advice\n\nBody text.")
        mock_db.engagement_context.insert.assert_called_once()
        row = mock_db.engagement_context.insert.call_args.args[0]
        assert row["client_id"] == "client-1"
        assert row["client_ref"] == "Client A"
        assert row["document_id"] == "doc-1"
        assert row["document_type"] == "advice_memo"
        assert row["title"] == "Memo"
        assert row["content"] == "# Advice\n\nBody text."
        assert row["embedding"] == embedding
    finally:
        app.dependency_overrides.clear()


def test_generate_document_skips_engagement_context_for_non_approved_type(client):
    from taxflow.main import app
    from taxflow.routers import documents as documents_router

    fake_client = {"id": "client-1", "email": "a@b.com.au", "business_name": "Acme"}
    mock_db = _mock_db()
    _override(fake_client, mock_db)

    fake_state = {"result_md": "letter body"}
    try:
        with patch.object(
            documents_router.document_graph, "ainvoke", new=AsyncMock(return_value=fake_state)
        ), patch.object(
            documents_router, "embed", new=AsyncMock(return_value=[0.1] * 1536)
        ) as mock_embed:
            # client_letter is NOT in the approved engagement-context type set.
            resp = client.post(
                "/documents/generate",
                json={
                    "document_type": "client_letter",
                    "title": "Letter",
                    "content_md": "raw",
                    "client_ref": "Client A",
                },
            )
        assert resp.status_code == 200
        mock_embed.assert_not_awaited()
        mock_db.engagement_context.insert.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_generate_document_embed_failure_does_not_block_save(client):
    from taxflow.main import app
    from taxflow.routers import documents as documents_router

    fake_client = {"id": "client-1", "email": "a@b.com.au", "business_name": "Acme"}
    mock_db = _mock_db()
    _override(fake_client, mock_db)

    fake_state = {"result_md": "memo body"}
    try:
        with patch.object(
            documents_router.document_graph, "ainvoke", new=AsyncMock(return_value=fake_state)
        ), patch.object(
            documents_router, "embed", new=AsyncMock(side_effect=RuntimeError("embed down"))
        ):
            resp = client.post(
                "/documents/generate",
                json={
                    "document_type": "advice_memo",
                    "title": "Memo",
                    "content_md": "raw",
                    "client_ref": "Client A",
                },
            )
        # The document is still saved and returned; the embed failure is swallowed.
        assert resp.status_code == 200
        assert resp.json()["id"] == "doc-1"
        mock_db.documents.insert.assert_called_once()
        mock_db.engagement_context.insert.assert_not_called()
    finally:
        app.dependency_overrides.clear()


# --- engagement_search: client scoping ---------------------------------------


@pytest.mark.asyncio
async def test_engagement_search_filters_by_client_id_and_client_ref():
    from taxflow.adapters.vectorstore import pgvector
    from taxflow.adapters.vectorstore.pgvector import PgVectorStore

    fake_cur = MagicMock()
    fake_cur.fetchall.return_value = [
        {"id": 5, "title": "Prior memo", "content": "body", "sim": 0.71}
    ]
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur
    fake_conn.__enter__ = MagicMock(return_value=fake_conn)
    fake_conn.__exit__ = MagicMock(return_value=False)
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=fake_conn)
    cm.__exit__ = MagicMock(return_value=False)

    with patch.object(pgvector, "get_pg_conn", return_value=cm):
        hits = await PgVectorStore().engagement_search(
            embedding=[0.2] * 1536, client_id="cid", client_ref="Client A", limit=4
        )

    # SET LOCAL probes precedes the vector SELECT (so it isn't a no-op).
    first_sql = fake_cur.execute.call_args_list[0].args[0]
    assert "SET LOCAL ivfflat.probes" in first_sql
    second_sql = fake_cur.execute.call_args_list[1].args[0]
    params = fake_cur.execute.call_args_list[1].args[1]
    # Scoped to engagement_context by BOTH client_id AND client_ref, and only
    # rows that actually carry an embedding.
    assert "engagement_context" in second_sql
    assert "client_id = %s" in second_sql
    assert "client_ref = %s" in second_sql
    assert "embedding IS NOT NULL" in second_sql
    assert "<=>" in second_sql
    assert "cid" in params
    assert "Client A" in params

    # Row shape maps to the provider-agnostic VectorHit with the memo citation.
    assert hits[0]["id"] == "5"
    assert hits[0]["citation"] == "Engagement memo: Prior memo"
    assert hits[0]["score"] == pytest.approx(0.71)


# --- _retrieve_context: merge engagement hits when client_ref present ---------


def _authoritative(n):
    return [
        {"id": str(i), "citation": f"c{i}", "content": "x", "source_url": "", "score": 0.9 - i * 0.01}
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_retrieve_context_merges_engagement_hits_when_client_ref_present():
    from taxflow.config import settings
    from taxflow.services.agents import research

    agent = research.ResearchAgent()
    auth = _authoritative(3)
    engagement_hits = [
        {"id": "e1", "citation": "Engagement memo: Prior", "content": "memo",
         "source_url": "", "score": 0.5}
    ]

    engagement_search = AsyncMock(return_value=list(engagement_hits))
    with patch.object(research, "generate_candidates", new=AsyncMock(return_value=list(auth))), \
        patch.object(research, "rerank_candidates", new=AsyncMock(side_effect=lambda q, c, **k: c)), \
        patch.object(research, "generate_historical_candidates", new=AsyncMock(return_value=[])), \
        patch.object(agent, "_firm_knowledge_search", new=AsyncMock(return_value=[])), \
        patch.object(providers_vector_store(), "engagement_search", new=engagement_search):
        chunks, signals = await agent._retrieve_context(
            "q", "cid", embedding=[0.1] * 1536, client_ref="Client A"
        )

    engagement_search.assert_awaited_once()
    assert engagement_search.await_args.kwargs["client_ref"] == "Client A"
    assert engagement_search.await_args.kwargs["client_id"] == "cid"
    # The engagement memo participates in the merged pool.
    ids = [c["id"] for c in chunks]
    assert "e1" in ids
    # ENGAGEMENT_CHUNK_WEIGHT applied to the raw similarity.
    memo = next(c for c in chunks if c["id"] == "e1")
    assert memo["score"] == pytest.approx(0.5 * settings.ENGAGEMENT_CHUNK_WEIGHT)
    # Signals stay derived from the GLOBAL pool only.
    assert signals["num_chunks"] == 3


@pytest.mark.asyncio
async def test_retrieve_context_skips_engagement_when_no_client_ref():
    from taxflow.services.agents import research

    agent = research.ResearchAgent()
    auth = _authoritative(3)

    engagement_search = AsyncMock(return_value=[])
    with patch.object(research, "generate_candidates", new=AsyncMock(return_value=list(auth))), \
        patch.object(research, "rerank_candidates", new=AsyncMock(side_effect=lambda q, c, **k: c)), \
        patch.object(research, "generate_historical_candidates", new=AsyncMock(return_value=[])), \
        patch.object(agent, "_firm_knowledge_search", new=AsyncMock(return_value=[])), \
        patch.object(providers_vector_store(), "engagement_search", new=engagement_search):
        chunks, _ = await agent._retrieve_context("q", "cid", embedding=[0.1] * 1536)

    # No client_ref → engagement search never runs, no engagement chunks.
    engagement_search.assert_not_awaited()
    assert [c["id"] for c in chunks] == ["0", "1", "2"]


@pytest.mark.asyncio
async def test_retrieve_context_skips_engagement_when_disabled(monkeypatch):
    from taxflow.config import settings
    from taxflow.services.agents import research

    monkeypatch.setattr(settings, "ENGAGEMENT_CONTEXT_ENABLED", False)
    agent = research.ResearchAgent()
    auth = _authoritative(3)

    engagement_search = AsyncMock(return_value=[])
    with patch.object(research, "generate_candidates", new=AsyncMock(return_value=list(auth))), \
        patch.object(research, "rerank_candidates", new=AsyncMock(side_effect=lambda q, c, **k: c)), \
        patch.object(research, "generate_historical_candidates", new=AsyncMock(return_value=[])), \
        patch.object(agent, "_firm_knowledge_search", new=AsyncMock(return_value=[])), \
        patch.object(providers_vector_store(), "engagement_search", new=engagement_search):
        chunks, _ = await agent._retrieve_context(
            "q", "cid", embedding=[0.1] * 1536, client_ref="Client A"
        )

    # Flag off → engagement search never runs even with a client_ref.
    engagement_search.assert_not_awaited()
    assert [c["id"] for c in chunks] == ["0", "1", "2"]


def providers_vector_store():
    """The memoised vector store instance used by _engagement_search (which calls
    providers.get_vector_store()). Patching engagement_search on this instance
    intercepts the adapter call without touching the DB."""
    from taxflow import providers

    return providers.get_vector_store()
