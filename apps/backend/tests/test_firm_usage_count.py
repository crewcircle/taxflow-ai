"""Task C5: firm-knowledge usage-count increment on the answer flow.

A firm chunk that is CITED in the answer triggers
FirmKnowledgeRepo.increment_usage with its id; a firm chunk that is NOT cited
does not. Also asserts trace.retrieval.firm_knowledge_used carries the cited
firm citations.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _firm_chunk(cid, citation):
    return {
        "id": cid,
        "citation": citation,
        "content": "firm content",
        "source_url": "",
        "score": 0.8,
    }


def _global_chunk(citation):
    return {
        "id": None,
        "citation": citation,
        "content": "law content",
        "source_url": "http://ato",
        "score": 0.7,
    }


@pytest.mark.asyncio
async def test_cited_firm_chunk_triggers_increment_usage():
    from taxflow.services.agents import research

    agent = research.ResearchAgent()

    chunks = [
        _global_chunk("ITAA 1997 s8-1"),           # [1] global, cited
        _firm_chunk("fk-1", "Firm knowledge: Memo A"),  # [2] firm, cited
    ]
    # Answer cites [1] and [2] → the firm chunk [2] is cited.
    fake_llm = MagicMock()
    fake_llm.generate = AsyncMock()

    mock_repos = MagicMock()

    with patch.object(
        agent, "_prepare",
        new=AsyncMock(return_value=("ctx", "", chunks, {"num_chunks": 2}, None, 0)),
    ), patch.object(
        agent, "_generate",
        new=AsyncMock(return_value=("Answer [1][2]", {"input_tokens": 1, "output_tokens": 1})),
    ), patch(
        "taxflow.providers.get_relational_data", return_value=mock_repos
    ):
        result = await agent.run("q", "cid", embedding=[0.1] * 1536)

    # increment_usage called with ONLY the cited firm chunk id.
    mock_repos.firm_knowledge.increment_usage.assert_called_once_with("cid", ["fk-1"])
    # trace surfaces the cited firm citation.
    assert result["trace"]["retrieval"]["firm_knowledge_used"] == [
        "Firm knowledge: Memo A"
    ]


@pytest.mark.asyncio
async def test_non_cited_firm_chunk_does_not_increment():
    from taxflow.services.agents import research

    agent = research.ResearchAgent()

    chunks = [
        _global_chunk("ITAA 1997 s8-1"),           # [1] global, cited
        _firm_chunk("fk-1", "Firm knowledge: Memo A"),  # [2] firm, NOT cited
    ]
    mock_repos = MagicMock()

    with patch.object(
        agent, "_prepare",
        new=AsyncMock(return_value=("ctx", "", chunks, {"num_chunks": 2}, None, 0)),
    ), patch.object(
        agent, "_generate",
        new=AsyncMock(return_value=("Answer [1]", {"input_tokens": 1, "output_tokens": 1})),
    ), patch(
        "taxflow.providers.get_relational_data", return_value=mock_repos
    ):
        result = await agent.run("q", "cid", embedding=[0.1] * 1536)

    # The firm chunk was retrieved but not cited → no usage bump at all.
    mock_repos.firm_knowledge.increment_usage.assert_not_called()
    # No cited firm citations → firm_knowledge_used stays None.
    assert result["trace"]["retrieval"]["firm_knowledge_used"] is None
