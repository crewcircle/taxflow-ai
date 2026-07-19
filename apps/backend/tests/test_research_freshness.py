"""Tests for Task B3: historical/superseded generation labeling, knowledge_as_of
freshness stamp, and the firm-items trace fragment.

The pure helpers (``_build_context_string``, ``_compute_knowledge_as_of``,
``build_firm_items``) and the SYSTEM_PROMPT rule are unit-tested directly. The
retrieval-owned agent test drives ``ResearchAgent.run()`` with mocked retrieval
(matching the ``test_research_routing.py`` mocking style) to prove a historical
chunk flows through to the trace candidates AND that ``knowledge_as_of`` is
populated from the cited current chunk.
"""
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from taxflow.config import settings
from taxflow.services.agents.research import (
    SYSTEM_PROMPT,
    ResearchAgent,
    _compute_knowledge_as_of,
    build_firm_items,
)


# --- _build_context_string: historical labeling ------------------------------


def test_context_string_labels_historical_with_superseded_by():
    agent = ResearchAgent()
    chunks = [
        {
            "citation": "TR 2019/1",
            "source_url": "http://x",
            "content": "old position",
            "is_historical": True,
            "superseded_by": "TR 2024/1",
        }
    ]
    ctx, _cmap = agent._build_context_string(chunks)
    assert (
        "[HISTORICAL — superseded by TR 2024/1, do not treat as current law] "
        in ctx
    )
    # The real citation/content still render after the prefix.
    assert "Citation: TR 2019/1" in ctx
    assert "old position" in ctx


def test_context_string_labels_historical_without_superseded_by():
    agent = ResearchAgent()
    chunks = [
        {
            "citation": "TR 2019/1",
            "source_url": "http://x",
            "content": "old position",
            "is_historical": True,
            "superseded_by": None,
        }
    ]
    ctx, _cmap = agent._build_context_string(chunks)
    assert "[HISTORICAL — superseded, do not treat as current law] " in ctx
    # The lineage variant must NOT appear when superseded_by is None.
    assert "superseded by" not in ctx


def test_context_string_current_chunk_unlabelled():
    agent = ResearchAgent()
    chunks = [
        {
            "citation": "TR 2024/1",
            "source_url": "http://x",
            "content": "current position",
        }
    ]
    ctx, _cmap = agent._build_context_string(chunks)
    assert "HISTORICAL" not in ctx
    # Authoritative chunks render exactly as before: "[1] Citation: ...".
    assert ctx.startswith("[1] Citation: TR 2024/1")


# --- _compute_knowledge_as_of ------------------------------------------------


def test_knowledge_as_of_returns_newest_cited_current_date():
    chunks = [
        {"citation": "A", "last_scraped_at": datetime(2026, 1, 10)},
        {"citation": "B", "last_scraped_at": datetime(2026, 5, 20)},
        {"citation": "C", "last_scraped_at": datetime(2026, 3, 1)},
    ]
    citations = [{"citation": "A"}, {"citation": "B"}]
    # Newest among CITED (A, B) is B's 2026-05-20; C is not cited.
    assert _compute_knowledge_as_of(chunks, citations) == "2026-05-20"


def test_knowledge_as_of_ignores_historical_chunks():
    chunks = [
        {"citation": "A", "last_scraped_at": datetime(2026, 1, 10)},
        {
            "citation": "OLD",
            "last_scraped_at": datetime(2027, 12, 31),
            "is_historical": True,
        },
    ]
    citations = [{"citation": "A"}, {"citation": "OLD"}]
    # The (newer) historical chunk is ignored — only the current cited chunk.
    assert _compute_knowledge_as_of(chunks, citations) == "2026-01-10"


def test_knowledge_as_of_ignores_firm_none_dates():
    chunks = [
        {"citation": "A", "last_scraped_at": datetime(2026, 2, 2)},
        {"citation": "Firm knowledge: memo", "last_scraped_at": None},
    ]
    citations = [{"citation": "A"}, {"citation": "Firm knowledge: memo"}]
    # Firm chunk carries last_scraped_at=None -> ignored.
    assert _compute_knowledge_as_of(chunks, citations) == "2026-02-02"


def test_knowledge_as_of_none_when_no_current_chunk_cited():
    chunks = [
        {"citation": "A", "last_scraped_at": datetime(2026, 2, 2)},
        {
            "citation": "OLD",
            "last_scraped_at": datetime(2025, 1, 1),
            "is_historical": True,
        },
    ]
    # Only the historical chunk is cited; A is retrieved but not cited.
    citations = [{"citation": "OLD"}]
    assert _compute_knowledge_as_of(chunks, citations) is None


def test_knowledge_as_of_none_when_nothing_cited():
    chunks = [{"citation": "A", "last_scraped_at": datetime(2026, 2, 2)}]
    assert _compute_knowledge_as_of(chunks, []) is None


# --- build_firm_items --------------------------------------------------------


def test_build_firm_items_flags_and_count():
    chunks = [
        {"citation": "TR 2024/1"},  # global, not a firm item
        {"citation": "Firm knowledge: onboarding memo"},
        {"citation": "Firm knowledge: fee policy"},
    ]
    citations = [{"citation": "Firm knowledge: onboarding memo"}]
    result = build_firm_items(chunks, citations)

    assert result["firm_items"] == [
        {"citation": "Firm knowledge: onboarding memo", "cited_in_answer": True},
        {"citation": "Firm knowledge: fee policy", "cited_in_answer": False},
    ]
    # firm_items_used counts only the cited firm item.
    assert result["firm_items_used"] == 1


def test_build_firm_items_empty_when_no_firm_chunks():
    chunks = [{"citation": "TR 2024/1"}, {"citation": "s25-10 ITAA97"}]
    result = build_firm_items(chunks, [{"citation": "TR 2024/1"}])
    assert result == {"firm_items": [], "firm_items_used": 0}


# --- SYSTEM_PROMPT contains the historical-use rule --------------------------


def test_system_prompt_has_historical_use_rule():
    # Normalise whitespace so line-wrapping in the prompt doesn't break matching.
    prompt = " ".join(SYSTEM_PROMPT.lower().split())
    assert "historical" in prompt
    # The rule must state historical/superseded sources are not current law and
    # are only for explaining how a position changed over time.
    assert "not current law" in prompt
    assert "changed over time" in prompt


# --- retrieval-owned agent test: historical chunk -> trace + freshness --------


@pytest.mark.asyncio
async def test_run_trace_carries_historical_candidate_and_knowledge_as_of():
    agent = ResearchAgent()
    chunks = [
        {
            "id": "1",
            "citation": "TR 2024/1",
            "content": "current",
            "source_url": "http://x",
            "score": 0.5,
            "last_scraped_at": datetime(2026, 6, 30),
        },
        {
            "id": "2",
            "citation": "TR 2019/1",
            "content": "old",
            "source_url": "http://y",
            "score": 0.2,
            "is_historical": True,
            "is_superseded": True,
            "superseded_by": "TR 2024/1",
            "last_scraped_at": datetime(2019, 1, 1),
        },
    ]

    with patch.object(
        agent,
        "_retrieve_context",
        new=AsyncMock(
            return_value=(
                chunks,
                {"num_chunks": 2, "top_score": 0.5, "insufficient": False},
            )
        ),
    ), patch.object(
        agent,
        "_generate",
        # Answer cites [1] (current) only.
        new=AsyncMock(
            return_value=(
                "Current law is X [1].",
                {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                },
            )
        ),
    ):
        result = await agent.run(question="q", client_id="cid")

    candidates = result["trace"]["retrieval"]["candidates"]
    hist = candidates[1]
    assert hist["is_historical"] is True
    assert hist["is_superseded"] is True
    assert hist["superseded_by"] == "TR 2024/1"

    # knowledge_as_of comes from the CITED current chunk (TR 2024/1), not the
    # historical one (which is both uncited and ignored).
    assert result["trace"]["retrieval"]["knowledge_as_of"] == "2026-06-30"
    assert result["trace"]["retrieval"]["historical_pool_size"] == 1
