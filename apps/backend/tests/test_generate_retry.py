"""ResearchAgent._generate retries once on an empty completion (offline).

Observed on OpenRouter/DeepSeek during the RAG-quality experiment: a provider
can return a completion with no error and empty content. Previously that
became a permanent blank answer; _generate now retries once before giving up.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from taxflow.ports.llm import LLMResult, Usage
from taxflow.services.agents.research import ResearchAgent


@pytest.mark.asyncio
async def test_generate_retries_once_on_empty_completion():
    fake_llm = AsyncMock()
    fake_llm.generate = AsyncMock(
        side_effect=[
            LLMResult(text="", usage=Usage(input_tokens=1, output_tokens=0)),
            LLMResult(text="Real answer [1].", usage=Usage(input_tokens=1, output_tokens=5)),
        ]
    )
    agent = ResearchAgent(llm=fake_llm)

    answer, usage = await agent._generate("q", "ctx", "model")

    assert answer == "Real answer [1]."
    assert fake_llm.generate.await_count == 2
    # Usage reflects the successful (second) call, not the empty first one.
    assert usage["output_tokens"] == 5


@pytest.mark.asyncio
async def test_generate_does_not_retry_on_non_empty_completion():
    fake_llm = AsyncMock()
    fake_llm.generate = AsyncMock(
        return_value=LLMResult(text="Answer [1].", usage=Usage(input_tokens=1, output_tokens=3))
    )
    agent = ResearchAgent(llm=fake_llm)

    answer, _usage = await agent._generate("q", "ctx", "model")

    assert answer == "Answer [1]."
    assert fake_llm.generate.await_count == 1


@pytest.mark.asyncio
async def test_generate_gives_up_after_one_retry_if_still_empty():
    fake_llm = AsyncMock()
    fake_llm.generate = AsyncMock(
        return_value=LLMResult(text="", usage=Usage(input_tokens=1, output_tokens=0))
    )
    agent = ResearchAgent(llm=fake_llm)

    answer, _usage = await agent._generate("q", "ctx", "model")

    assert answer == ""
    assert fake_llm.generate.await_count == 2
