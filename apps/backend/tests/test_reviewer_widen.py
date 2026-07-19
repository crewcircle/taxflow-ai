"""Tests for reviewer-driven widened retrieval (Task C3).

The corrective pass widens the candidate pool by threading ``pool_scale=2`` as a
PARAMETER through retrieval — it must NEVER mutate the global pool ``settings``
(so concurrent requests can never inherit a widened pool). These tests assert
the effective pool sizes that reach the vector store AND that the global config
values are unchanged before/after the call.
"""
from unittest.mock import AsyncMock, patch

import pytest

from taxflow import providers
from taxflow.config import settings
from taxflow.ports.llm import LLMResult, Usage
from taxflow.services.agents.research import ResearchAgent
from taxflow.services.knowledge import retrieval


class _FakeVectorStore:
    """Fake VectorStorePort capturing the limits passed to each search."""

    def __init__(self):
        self.semantic_search = AsyncMock(return_value=[])
        self.text_search = AsyncMock(return_value=[])
        self.firm_search = AsyncMock(return_value=[])
        self.historical_search = AsyncMock(return_value=[])
        self.engagement_search = AsyncMock(return_value=[])


class _FakeLLM:
    async def generate(self, **kwargs):
        return LLMResult(text="Corrected answer [1]", usage=Usage(input_tokens=10, output_tokens=5))


@pytest.mark.asyncio
async def test_widen_threads_pool_scale_2_without_mutating_settings():
    store = _FakeVectorStore()
    agent = ResearchAgent(llm=_FakeLLM())

    original_pool = settings.RERANK_CANDIDATE_POOL
    original_global = settings.RETRIEVAL_GLOBAL_POOL
    original_firm = settings.RETRIEVAL_FIRM_POOL

    with patch.object(providers, "get_vector_store", return_value=store), patch.object(
        retrieval, "embed", new=AsyncMock(return_value=[0.0] * 1536)
    ):
        result = await agent.regenerate_with_feedback(
            "q",
            "cid",
            issues=[{"issue": "wrong section"}],
            embedding=[0.1] * 1536,
            widen=True,
        )

    # The effective pool sizes reaching the vector store are doubled (pool_scale=2)
    # for THIS call: each of semantic/text search asks for RERANK_CANDIDATE_POOL*2,
    # and the firm search for RETRIEVAL_FIRM_POOL*2.
    assert store.semantic_search.await_args.kwargs["limit"] == original_pool * 2
    assert store.text_search.await_args.kwargs["limit"] == original_pool * 2
    assert store.firm_search.await_args.kwargs["limit"] == original_firm * 2

    # The global pool settings are NEVER mutated — they read back exactly as
    # before, so concurrent requests keep their own (un-widened) pools.
    assert settings.RERANK_CANDIDATE_POOL == original_pool
    assert settings.RETRIEVAL_GLOBAL_POOL == original_global
    assert settings.RETRIEVAL_FIRM_POOL == original_firm

    # The widen fired → re_retrieval reason is reviewer_flag, and re_retrieved is
    # set so A1's _build_final_trace records re_retrieval.fired.
    assert result["re_retrieval"] == {"fired": True, "reason": "reviewer_flag"}
    assert result["re_retrieved"] is True


@pytest.mark.asyncio
async def test_no_widen_uses_base_pool_and_reports_not_fired():
    store = _FakeVectorStore()
    agent = ResearchAgent(llm=_FakeLLM())

    with patch.object(providers, "get_vector_store", return_value=store), patch.object(
        retrieval, "embed", new=AsyncMock(return_value=[0.0] * 1536)
    ):
        result = await agent.regenerate_with_feedback(
            "q",
            "cid",
            issues=[{"issue": "wrong section"}],
            embedding=[0.1] * 1536,
            widen=False,
        )

    # No widen (pool_scale=1) → base pool sizes reach the store.
    assert store.semantic_search.await_args.kwargs["limit"] == settings.RERANK_CANDIDATE_POOL
    assert store.firm_search.await_args.kwargs["limit"] == settings.RETRIEVAL_FIRM_POOL

    assert result["re_retrieval"] == {"fired": False}
    assert result["re_retrieved"] is False


@pytest.mark.asyncio
async def test_widen_disabled_by_flag_does_not_fire(monkeypatch):
    monkeypatch.setattr(settings, "REVIEWER_WIDEN_ENABLED", False)
    store = _FakeVectorStore()
    agent = ResearchAgent(llm=_FakeLLM())

    with patch.object(providers, "get_vector_store", return_value=store), patch.object(
        retrieval, "embed", new=AsyncMock(return_value=[0.0] * 1536)
    ):
        result = await agent.regenerate_with_feedback(
            "q",
            "cid",
            issues=[{"issue": "wrong section"}],
            embedding=[0.1] * 1536,
            widen=True,
        )

    # widen requested but the flag is off → base pool, not fired.
    assert store.semantic_search.await_args.kwargs["limit"] == settings.RERANK_CANDIDATE_POOL
    assert result["re_retrieval"] == {"fired": False}
    assert result["re_retrieved"] is False
