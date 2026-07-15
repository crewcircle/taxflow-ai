"""Tests for retrieval embedding reuse and pgvector probes tuning (Tasks A4/A5)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from taxflow.config import settings
from taxflow.services.knowledge import retrieval


@pytest.mark.asyncio
async def test_hybrid_search_reuses_provided_embedding():
    vec = [0.3] * 1536

    with patch.object(retrieval, "embed", new=AsyncMock()) as mock_embed, patch.object(
        retrieval, "_semantic_search", return_value=[]
    ), patch.object(retrieval, "_text_search", return_value=[]):
        await retrieval.hybrid_search("q", top_k=8, embedding=vec)

    # A caller-supplied vector must be reused; no extra OpenAI embed round trip.
    mock_embed.assert_not_awaited()


@pytest.mark.asyncio
async def test_hybrid_search_embeds_when_no_embedding_given():
    with patch.object(retrieval, "embed", new=AsyncMock(return_value=[0.0] * 1536)) as mock_embed, patch.object(
        retrieval, "_semantic_search", return_value=[]
    ), patch.object(retrieval, "_text_search", return_value=[]):
        await retrieval.hybrid_search("q", top_k=8)

    mock_embed.assert_awaited_once()


def test_semantic_search_sets_probes_in_transaction():
    fake_cur = MagicMock()
    fake_cur.fetchall.return_value = []
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur
    fake_conn.__enter__ = MagicMock(return_value=fake_conn)
    fake_conn.__exit__ = MagicMock(return_value=False)

    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=fake_conn)
    cm.__exit__ = MagicMock(return_value=False)

    with patch.object(retrieval, "get_pg_conn", return_value=cm):
        retrieval._semantic_search([0.1] * 1536, None, 20)

    # The explicit transaction must be entered so SET LOCAL isn't a no-op, and the
    # probes statement must precede the vector SELECT.
    fake_conn.__enter__.assert_called_once()
    first_sql = fake_cur.execute.call_args_list[0].args[0]
    assert "SET LOCAL ivfflat.probes" in first_sql
    assert fake_cur.execute.call_args_list[0].args[1] == (settings.IVFFLAT_PROBES,)
    second_sql = fake_cur.execute.call_args_list[1].args[0]
    assert "knowledge_chunks" in second_sql
