"""Tests for the per-client DB-backed answer cache (Task B3)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from taxflow.config import settings
from taxflow.services import answer_cache


def test_normalise_question_is_stable():
    assert answer_cache.normalise_question("  What is the CGT discount?  ") == "what is the cgt discount"
    assert answer_cache.normalise_question("What is the CGT discount") == answer_cache.normalise_question(
        "  what   is the CGT DISCOUNT?"
    )


@pytest.mark.asyncio
async def test_cache_key_includes_knowledge_version_and_client(monkeypatch):
    monkeypatch.setattr(settings, "ANSWER_CACHE_ENABLED", True)
    captured = {}

    def fake_get_sync(client_id, question_norm, version):
        captured["client_id"] = client_id
        captured["question_norm"] = question_norm
        captured["version"] = version
        return None

    with patch.object(answer_cache, "get_knowledge_version", new=AsyncMock(return_value=7)), patch.object(
        answer_cache, "_get_sync", side_effect=fake_get_sync
    ):
        await answer_cache.get_cached_answer("client-A", "What is the CGT discount?")

    assert captured["client_id"] == "client-A"
    assert captured["version"] == 7
    assert captured["question_norm"] == "what is the cgt discount"


@pytest.mark.asyncio
async def test_version_bump_forces_a_miss(monkeypatch):
    monkeypatch.setattr(settings, "ANSWER_CACHE_ENABLED", True)

    # Simulate a store at version 1, then a lookup at version 2 (after an ingest
    # bumped the token) — the key differs so it must miss.
    store = {}

    def fake_get_sync(client_id, question_norm, version):
        return store.get((client_id, question_norm, version))

    def fake_store_sync(client_id, question_norm, version, result):
        store[(client_id, question_norm, version)] = result

    with patch.object(answer_cache, "_get_sync", side_effect=fake_get_sync), patch.object(
        answer_cache, "_store_sync", side_effect=fake_store_sync
    ):
        with patch.object(answer_cache, "get_knowledge_version", new=AsyncMock(return_value=1)):
            await answer_cache.store_answer("c", "q", {"answer": "v1"})
            hit = await answer_cache.get_cached_answer("c", "q")
            assert hit == {"answer": "v1"}

        # Ingest bumps version -> next lookup misses.
        with patch.object(answer_cache, "get_knowledge_version", new=AsyncMock(return_value=2)):
            miss = await answer_cache.get_cached_answer("c", "q")
            assert miss is None


@pytest.mark.asyncio
async def test_cache_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(settings, "ANSWER_CACHE_ENABLED", False)
    with patch.object(answer_cache, "_get_sync") as mock_get:
        assert await answer_cache.get_cached_answer("c", "q") is None
    mock_get.assert_not_called()


def test_bump_knowledge_version_increments():
    fake_cur = MagicMock()
    fake_cur.fetchone.return_value = [5]
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur
    fake_conn.__enter__ = MagicMock(return_value=fake_conn)
    fake_conn.__exit__ = MagicMock(return_value=False)
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=fake_conn)
    cm.__exit__ = MagicMock(return_value=False)

    with patch("taxflow.services.answer_cache.get_pg_conn", return_value=cm):
        assert answer_cache.bump_knowledge_version() == 5
    sql = fake_cur.execute.call_args.args[0]
    assert "version = version + 1" in sql
