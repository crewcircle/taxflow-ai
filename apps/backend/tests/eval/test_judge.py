"""Offline tests for the LLM-as-judge (Task B2).

Injects a MagicMock LLM (mirrors test_rerank.py / test_verify_gate.py) so no paid
call is ever made. Asserts the model kwarg is the RESOLVED model string (not the
bare tier), the dict bridge, and the tolerant-fallback path.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from taxflow import providers
from taxflow.config import settings
from taxflow.ports.llm import StructuredParseError
from taxflow.services.eval.judge import EvalJudge
from taxflow.services.eval.models import JudgeScore


def _judge_score(**overrides):
    base = dict(
        faithfulness=5,
        relevance=4,
        citation_correctness=5,
        hallucination=False,
        unsupported_claims=[],
        rationale="Well grounded.",
    )
    base.update(overrides)
    return JudgeScore(**base)


@pytest.mark.asyncio
async def test_score_one_structured_call_resolved_model_and_dict_bridge(monkeypatch):
    monkeypatch.setattr(settings, "EVAL_JUDGE_TIER", "sonnet")
    fake_llm = MagicMock()
    fake_llm.generate_structured = AsyncMock(return_value=_judge_score())
    monkeypatch.setattr("taxflow.providers.get_llm", lambda: fake_llm)

    judge = EvalJudge()
    result = await judge.score(
        question="q",
        answer="answer [1]",
        retrieved_context="[1] Citation: ITAA 1997",
        citations=[{"citation": "ITAA 1997", "excerpt": "..."}],
    )

    fake_llm.generate_structured.assert_awaited_once()
    kwargs = fake_llm.generate_structured.await_args.kwargs
    # The model kwarg must be the RESOLVED model string, not the bare tier.
    assert kwargs["model"] == providers.resolve_model("sonnet")
    assert kwargs["model"] != "sonnet"
    assert kwargs["output_model"] is JudgeScore
    assert kwargs["temperature"] == 0
    # Dict bridge.
    assert isinstance(result, dict)
    assert result["faithfulness"] == 5
    assert result["hallucination"] is False


@pytest.mark.asyncio
async def test_score_injected_llm_used_directly(monkeypatch):
    # EvalJudge(llm=...) should NOT call the composition root.
    monkeypatch.setattr(
        "taxflow.providers.get_llm",
        lambda: (_ for _ in ()).throw(AssertionError("get_llm should not be called")),
    )
    fake_llm = MagicMock()
    fake_llm.generate_structured = AsyncMock(return_value=_judge_score(relevance=3))
    judge = EvalJudge(llm=fake_llm)
    result = await judge.score(
        question="q", answer="a", retrieved_context="ctx", citations=[]
    )
    assert result["relevance"] == 3


@pytest.mark.asyncio
async def test_score_tolerant_fallback_on_structured_parse_error(monkeypatch):
    monkeypatch.setattr(settings, "EVAL_JUDGE_TIER", "sonnet")
    fake_llm = MagicMock()
    fake_llm.generate_structured = AsyncMock(side_effect=StructuredParseError("bad"))
    # Plain generation returns fenced JSON the tolerant parser recovers.
    plain = MagicMock()
    plain.text = '```json\n{"faithfulness": 3, "relevance": 3, "citation_correctness": 2, "hallucination": true, "unsupported_claims": ["x"], "rationale": "recovered"}\n```'
    fake_llm.generate = AsyncMock(return_value=plain)
    monkeypatch.setattr("taxflow.providers.get_llm", lambda: fake_llm)

    judge = EvalJudge()
    result = await judge.score(
        question="q", answer="a", retrieved_context="ctx", citations=[]
    )
    fake_llm.generate.assert_awaited_once()
    # generate() must also receive the resolved model, never the bare tier.
    assert fake_llm.generate.await_args.kwargs["model"] == providers.resolve_model("sonnet")
    assert result["faithfulness"] == 3
    assert result["hallucination"] is True


@pytest.mark.asyncio
async def test_score_parse_error_verdict_when_unrecoverable(monkeypatch):
    fake_llm = MagicMock()
    fake_llm.generate_structured = AsyncMock(side_effect=StructuredParseError("bad"))
    plain = MagicMock()
    plain.text = "not json at all"
    fake_llm.generate = AsyncMock(return_value=plain)
    monkeypatch.setattr("taxflow.providers.get_llm", lambda: fake_llm)

    judge = EvalJudge()
    result = await judge.score(
        question="q", answer="a", retrieved_context="ctx", citations=[]
    )
    assert result["rationale"] == "parse_error"
    assert result["verdict"] == "parse_error"
