"""Tests for the pgvector VectorStorePort adapter (Task A3).

``get_pg_conn`` is mocked so no real DB is touched; we assert the SQL carries the
pgvector-specific bits (``<=>`` cosine, ``ivfflat.probes``) and the SELECT column
list includes ``last_scraped_at``/``source_type`` (added by a recent merge).
"""
from unittest.mock import MagicMock, patch

import pytest

from taxflow.adapters.vectorstore import pgvector
from taxflow.adapters.vectorstore.pgvector import PgVectorStore
from taxflow.config import settings
from taxflow.ports.vectorstore import VectorStorePort


def _fake_conn(rows):
    fake_cur = MagicMock()
    fake_cur.fetchall.return_value = rows
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur
    fake_conn.__enter__ = MagicMock(return_value=fake_conn)
    fake_conn.__exit__ = MagicMock(return_value=False)
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=fake_conn)
    cm.__exit__ = MagicMock(return_value=False)
    return cm, fake_cur


def test_adapter_satisfies_vectorstore_port():
    assert isinstance(PgVectorStore(), VectorStorePort)


@pytest.mark.asyncio
async def test_semantic_search_sets_probes_and_uses_cosine():
    cm, fake_cur = _fake_conn([])
    with patch.object(pgvector, "get_pg_conn", return_value=cm):
        await PgVectorStore().semantic_search(embedding=[0.1] * 1536, source_types=None, limit=20)

    # SET LOCAL probes must precede the vector SELECT (so it isn't a no-op).
    first_sql = fake_cur.execute.call_args_list[0].args[0]
    assert "SET LOCAL ivfflat.probes" in first_sql
    assert fake_cur.execute.call_args_list[0].args[1] == (settings.IVFFLAT_PROBES,)
    second_sql = fake_cur.execute.call_args_list[1].args[0]
    assert "knowledge_chunks" in second_sql
    assert "<=>" in second_sql
    assert "last_scraped_at" in second_sql
    assert "source_type" in second_sql


@pytest.mark.asyncio
async def test_text_search_uses_fts_columns():
    cm, fake_cur = _fake_conn([])
    with patch.object(pgvector, "get_pg_conn", return_value=cm):
        await PgVectorStore().text_search(query="cgt", source_types=None, limit=20)

    sql = fake_cur.execute.call_args_list[0].args[0]
    assert "to_tsvector" in sql
    assert "plainto_tsquery" in sql
    assert "ts_rank" in sql
    assert "last_scraped_at" in sql
    assert "source_type" in sql


@pytest.mark.asyncio
async def test_historical_search_scopes_to_superseded_and_sets_probes():
    cm, fake_cur = _fake_conn([])
    with patch.object(pgvector, "get_pg_conn", return_value=cm):
        await PgVectorStore().historical_search(
            embedding=[0.1] * 1536, source_types=None, limit=3
        )

    # SET LOCAL probes must precede the vector SELECT (so it isn't a no-op).
    first_sql = fake_cur.execute.call_args_list[0].args[0]
    assert "SET LOCAL ivfflat.probes" in first_sql
    assert fake_cur.execute.call_args_list[0].args[1] == (settings.IVFFLAT_PROBES,)
    second_sql = fake_cur.execute.call_args_list[1].args[0]
    # Scoped to superseded chunks, carrying lineage, ordered by cosine distance.
    assert "is_current = false" in second_sql
    assert "superseded_by" in second_sql
    assert "<=>" in second_sql
    assert "knowledge_chunks" in second_sql


@pytest.mark.asyncio
async def test_firm_search_maps_rows_to_vector_hits():
    cm, fake_cur = _fake_conn([{"id": 1, "file_name": "notes", "content": "c", "sim": 0.42}])
    with patch.object(pgvector, "get_pg_conn", return_value=cm):
        hits = await PgVectorStore().firm_search(embedding=[0.2] * 1536, client_id="cid", limit=4)

    # SET LOCAL probes + cosine expression against firm_knowledge.
    first_sql = fake_cur.execute.call_args_list[0].args[0]
    assert "SET LOCAL ivfflat.probes" in first_sql
    second_sql = fake_cur.execute.call_args_list[1].args[0]
    assert "firm_knowledge" in second_sql
    assert "<=>" in second_sql

    # Raw similarity carried as score (weighting is applied by the service layer).
    assert hits[0]["id"] == "1"
    assert hits[0]["citation"] == "Firm knowledge: notes"
    assert hits[0]["score"] == pytest.approx(0.42)
    assert hits[0]["last_scraped_at"] is None
