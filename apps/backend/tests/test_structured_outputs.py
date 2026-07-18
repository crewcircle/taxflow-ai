"""Structured-output tests for verify / classifier / rerank (Task A4).

Each service now routes its JSON generation through
``LLMPort.generate_structured``. We monkeypatch ``providers.get_llm`` to return a
fake whose ``generate_structured`` either returns a valid Pydantic model
(asserting the dict bridge / downstream shape) or raises ``StructuredParseError``
(asserting the tolerant fallback / ``parse_error`` path, and for rerank that the
input order is preserved).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from taxflow.config import settings
from taxflow.ports.llm import LLMResult, StructuredParseError
from taxflow.services.agents.models import (
    LetterClassification,
    RerankScores,
    VerificationIssue,
    VerificationResult,
)


def _fake_llm(**methods) -> MagicMock:
    llm = MagicMock()
    for name, impl in methods.items():
        setattr(llm, name, impl)
    return llm


# --- models: Literal / field shape -------------------------------------------


def test_verification_result_round_trips_to_dict():
    r = VerificationResult(
        overall_status="needs_correction",
        issues=[
            VerificationIssue(
                claim="c",
                issue="i",
                severity="critical",
                source_says="s",
                suggested_correction="fix",
            )
        ],
        unsupported_claims=["x"],
        overall_confidence=0.4,
    )
    d = r.model_dump()
    assert d["overall_status"] == "needs_correction"
    assert d["issues"][0]["severity"] == "critical"
    assert d["unsupported_claims"] == ["x"]


def test_letter_classification_matches_classifier_fields():
    c = LetterClassification(
        letter_type="penalty_notice",
        confidence=0.9,
        ato_reference="REF-1",
        taxpayer_name="Jane",
        deadline_days=14,
        amount_disputed=1234.5,
        key_issue="A penalty was issued.",
    )
    d = c.model_dump()
    assert d["letter_type"] == "penalty_notice"
    assert d["deadline_days"] == 14
    assert d["amount_disputed"] == 1234.5
    # Optional fields default to None.
    assert LetterClassification(
        letter_type="bas_discrepancy", confidence=0.5, key_issue="k"
    ).ato_reference is None


def test_letter_type_literal_in_sync_with_constant():
    from taxflow.services.agents.models import LetterType
    from taxflow.services.ato_correspondence.classifier import LETTER_TYPES

    assert set(LetterType.__args__) == set(LETTER_TYPES)


# --- verify: dict bridge + StructuredParseError -> parse_error ----------------


@pytest.mark.asyncio
async def test_verify_run_returns_dict_from_model(monkeypatch):
    from taxflow.services.agents.verify import VerifyAgent

    fake = _fake_llm(
        generate_structured=AsyncMock(
            return_value=VerificationResult(overall_status="verified", issues=[])
        )
    )
    monkeypatch.setattr("taxflow.providers.get_llm", lambda: fake)

    result = await VerifyAgent().run(draft="d", citations=[{"citation": "x"}], question="q")
    assert isinstance(result, dict)
    assert result["overall_status"] == "verified"
    # System prompt is passed through the cacheable_system() form.
    assert fake.generate_structured.await_args.kwargs["output_model"] is VerificationResult


@pytest.mark.asyncio
async def test_verify_run_parse_error_falls_back(monkeypatch):
    from taxflow.services.agents.verify import VerifyAgent

    fake = _fake_llm(
        generate_structured=AsyncMock(side_effect=StructuredParseError("bad")),
        generate=AsyncMock(return_value=LLMResult(text="not json at all")),
    )
    monkeypatch.setattr("taxflow.providers.get_llm", lambda: fake)

    result = await VerifyAgent().run(draft="d", citations=[], question="q")
    assert result["overall_status"] == "parse_error"
    assert result["issues"] == []


@pytest.mark.asyncio
async def test_verify_run_fallback_recovers_fenced_needs_correction(monkeypatch):
    """StructuredParseError + a fenced-JSON plain generation carrying a real
    needs_correction verdict must surface those issues (not an empty
    parse_error), so the corrective pass still fires."""
    from taxflow.services.agents.verify import VerifyAgent

    fenced = (
        "```json\n"
        '{"overall_status": "needs_correction", '
        '"issues": [{"claim": "wrong rate", "issue": "used 30%", '
        '"severity": "critical", "source_says": "27.5%", '
        '"suggested_correction": "use 27.5%"}]}\n'
        "```"
    )
    fake = _fake_llm(
        generate_structured=AsyncMock(side_effect=StructuredParseError("bad")),
        generate=AsyncMock(return_value=LLMResult(text=fenced)),
    )
    monkeypatch.setattr("taxflow.providers.get_llm", lambda: fake)

    result = await VerifyAgent().run(draft="d", citations=[], question="q")
    assert result["overall_status"] == "needs_correction"
    assert result["issues"][0]["severity"] == "critical"
    fake.generate.assert_awaited_once()


# --- classifier: dict bridge + fenced-JSON fallback ---------------------------


@pytest.mark.asyncio
async def test_classify_returns_dict_from_model(monkeypatch):
    from taxflow.services.ato_correspondence.classifier import ATOLetterClassifier

    fake = _fake_llm(
        generate_structured=AsyncMock(
            return_value=LetterClassification(
                letter_type="audit_initiation",
                confidence=0.8,
                key_issue="Audit started.",
            )
        )
    )
    monkeypatch.setattr("taxflow.providers.get_llm", lambda: fake)

    out = await ATOLetterClassifier().classify("some letter text")
    assert isinstance(out, dict)
    assert out["letter_type"] == "audit_initiation"


@pytest.mark.asyncio
async def test_classify_falls_back_to_fenced_json(monkeypatch):
    from taxflow.services.ato_correspondence.classifier import ATOLetterClassifier

    fenced = (
        "```json\n"
        '{"letter_type": "penalty_notice", "confidence": 0.7, "key_issue": "k"}\n'
        "```"
    )
    fake = _fake_llm(
        generate_structured=AsyncMock(side_effect=StructuredParseError("bad")),
        generate=AsyncMock(return_value=LLMResult(text=fenced)),
    )
    monkeypatch.setattr("taxflow.providers.get_llm", lambda: fake)

    out = await ATOLetterClassifier().classify("some letter text")
    assert out["letter_type"] == "penalty_notice"
    fake.generate.assert_awaited_once()


# --- rerank: model -> reorder; failure -> input order -------------------------


@pytest.mark.asyncio
async def test_rerank_reorders_from_model(monkeypatch):
    from taxflow.services.knowledge import retrieval

    monkeypatch.setattr(settings, "RERANK_DEPTH", 3)
    cands = [
        {"id": str(i), "citation": f"c{i}", "content": f"b{i}", "source_url": "", "score": 1.0}
        for i in range(3)
    ]
    fake = _fake_llm(
        generate_structured=AsyncMock(return_value=RerankScores(scores={0: 0.1, 1: 0.9, 2: 0.5}))
    )
    monkeypatch.setattr("taxflow.providers.get_llm", lambda: fake)

    out = await retrieval._llm_rerank("q", cands)
    assert [c["id"] for c in out[:3]] == ["1", "2", "0"]


@pytest.mark.asyncio
async def test_rerank_parse_error_uses_fenced_fallback(monkeypatch):
    from taxflow.services.knowledge import retrieval

    monkeypatch.setattr(settings, "RERANK_DEPTH", 3)
    cands = [
        {"id": str(i), "citation": f"c{i}", "content": f"b{i}", "source_url": "", "score": 1.0}
        for i in range(3)
    ]
    fake = _fake_llm(
        generate_structured=AsyncMock(side_effect=StructuredParseError("bad")),
        generate=AsyncMock(return_value=LLMResult(text='{"0": 0.2, "1": 0.9, "2": 0.5}')),
    )
    monkeypatch.setattr("taxflow.providers.get_llm", lambda: fake)

    out = await retrieval._llm_rerank("q", cands)
    assert [c["id"] for c in out[:3]] == ["1", "2", "0"]


@pytest.mark.asyncio
async def test_rerank_preserves_input_order_on_total_failure(monkeypatch):
    from taxflow.services.knowledge import retrieval

    monkeypatch.setattr(settings, "RERANK_DEPTH", 3)
    cands = [
        {"id": str(i), "citation": f"c{i}", "content": f"b{i}", "source_url": "", "score": 1.0}
        for i in range(3)
    ]
    fake = _fake_llm(generate_structured=AsyncMock(side_effect=RuntimeError("boom")))
    monkeypatch.setattr("taxflow.providers.get_llm", lambda: fake)

    out = await retrieval._llm_rerank("q", cands)
    # Rerank must NEVER fail retrieval: input candidate order is preserved.
    assert out == cands
