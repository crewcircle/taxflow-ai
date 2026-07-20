"""Tests for the clarify gate + classifier + effective-question folding (Phase 4).

Mirrors ``test_verify_gate.py``: a pure-Python pre-filter (``should_clarify``)
gates a Haiku ambiguity classifier (``ClarifyAgent.run``) that uses the
structured-output pattern with a tolerant, fail-open fallback.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from taxflow.config import settings
from taxflow.services.agents import clarify as clarify_mod
from taxflow.services.agents.clarify import ClarifyAgent, enforce_option_caps, should_clarify
from taxflow.services.agents.models import (
    ClarifyDecision,
    ClarifyOption,
    ClarifyQuestion,
)
from taxflow.services.agents.research import build_effective_question


STRONG_SIGNALS = {"num_chunks": 6, "top_score": 0.5, "insufficient": False}
WEAK_SIGNALS = {"num_chunks": 0, "top_score": 0.0, "insufficient": True}


# --- should_clarify: pure-Python pre-filter ----------------------------------


def test_should_clarify_false_when_clarifications_present():
    # This IS the round-trip answer — never re-clarify.
    assert (
        should_clarify(
            "How is CGT calculated on a share sale?",
            STRONG_SIGNALS,
            prior_turns_used=0,
            has_clarifications=True,
        )
        is False
    )


def test_should_clarify_false_on_follow_up_turn_with_context():
    # A follow-up turn already has session context loaded.
    assert (
        should_clarify(
            "gst?",
            WEAK_SIGNALS,
            prior_turns_used=2,
            has_clarifications=False,
        )
        is False
    )


def test_should_clarify_false_on_well_formed_question():
    q = "How should a discretionary trust treat a franked dividend for the 2024 year?"
    assert (
        should_clarify(q, STRONG_SIGNALS, prior_turns_used=0, has_clarifications=False)
        is False
    )


def test_should_clarify_true_on_very_short_question():
    assert (
        should_clarify("Div 7A", STRONG_SIGNALS, prior_turns_used=0, has_clarifications=False)
        is True
    )


def test_should_clarify_true_on_no_intent_verb():
    # A bare topic with no intent verb, longer than the short-word threshold.
    q = "capital gains tax small business concessions rollover asset"
    assert (
        should_clarify(q, STRONG_SIGNALS, prior_turns_used=0, has_clarifications=False)
        is True
    )


def test_should_clarify_true_on_weak_retrieval():
    q = "How do I apply the concession to this asset sale properly?"
    assert (
        should_clarify(q, WEAK_SIGNALS, prior_turns_used=0, has_clarifications=False)
        is True
    )


# --- enforce_option_caps -----------------------------------------------------


def test_enforce_option_caps_trims_questions_and_options(monkeypatch):
    monkeypatch.setattr(settings, "CLARIFY_MAX_QUESTIONS", 1)
    monkeypatch.setattr(settings, "CLARIFY_MAX_OPTIONS", 2)
    decision = ClarifyDecision(
        needs_clarification=True,
        confidence=0.9,
        questions=[
            ClarifyQuestion(
                prompt="q1",
                options=[
                    ClarifyOption(label=f"l{i}", value=f"v{i}") for i in range(4)
                ],
            ),
            ClarifyQuestion(prompt="q2", options=[ClarifyOption(label="l", value="v")]),
        ],
    )
    trimmed = enforce_option_caps(decision)
    assert len(trimmed.questions) == 1
    assert len(trimmed.questions[0].options) == 2


def test_enforce_option_caps_drops_optionless_questions_when_clarifying():
    # B1: a question with no options cannot render selectable chips, so it is
    # dropped from a needs_clarification decision.
    decision = ClarifyDecision(
        needs_clarification=True,
        confidence=0.9,
        questions=[
            ClarifyQuestion(prompt="no options", options=[]),
            ClarifyQuestion(
                prompt="has options",
                options=[ClarifyOption(label="l", value="v")],
            ),
        ],
    )
    result = enforce_option_caps(decision)
    assert result.needs_clarification is True
    assert [q.prompt for q in result.questions] == ["has options"]


def test_enforce_option_caps_fails_open_when_no_usable_questions():
    # B1: needs_clarification=True but every question is optionless (or there are
    # no questions at all) → fall open to answering, never a dead-end clarify card.
    decision = ClarifyDecision(
        needs_clarification=True,
        confidence=0.95,
        questions=[ClarifyQuestion(prompt="q", options=[])],
    )
    result = enforce_option_caps(decision)
    assert result.needs_clarification is False
    assert result.questions == []


def test_enforce_option_caps_fails_open_when_questions_empty():
    # B1: classifier claims it needs clarification but returns no questions.
    decision = ClarifyDecision(needs_clarification=True, confidence=0.95, questions=[])
    result = enforce_option_caps(decision)
    assert result.needs_clarification is False
    assert result.questions == []


# --- ClarifyAgent.run --------------------------------------------------------


@pytest.mark.asyncio
async def test_clarify_run_returns_structured_decision(monkeypatch):
    from taxflow import providers

    decision = ClarifyDecision(
        needs_clarification=True,
        confidence=0.8,
        questions=[
            ClarifyQuestion(
                prompt="Which entity?",
                options=[ClarifyOption(label="Company", value="company")],
            )
        ],
    )
    fake_llm = MagicMock()
    fake_llm.generate_structured = AsyncMock(return_value=decision)
    monkeypatch.setattr("taxflow.providers.get_llm", lambda: fake_llm)

    result = await ClarifyAgent().run("ambiguous?", STRONG_SIGNALS)
    assert isinstance(result, dict)
    assert result["needs_clarification"] is True
    assert result["questions"][0]["prompt"] == "Which entity?"
    assert fake_llm.generate_structured.await_args.kwargs["model"] == providers.resolve_model(
        "clarify"
    )


@pytest.mark.asyncio
async def test_clarify_run_fails_open_on_unparseable_fallback(monkeypatch):
    from taxflow.ports.llm import LLMResult, StructuredParseError, Usage

    fake_llm = MagicMock()
    fake_llm.generate_structured = AsyncMock(side_effect=StructuredParseError("bad"))
    fake_llm.generate = AsyncMock(
        return_value=LLMResult(text="not json at all", usage=Usage())
    )
    monkeypatch.setattr("taxflow.providers.get_llm", lambda: fake_llm)

    result = await ClarifyAgent().run("q?", STRONG_SIGNALS)
    # Fail open: answer directly (no clarification).
    assert result["needs_clarification"] is False
    assert result["questions"] == []


@pytest.mark.asyncio
async def test_clarify_run_recovers_via_tolerant_json_fallback(monkeypatch):
    from taxflow.ports.llm import LLMResult, StructuredParseError, Usage

    fenced = (
        "```json\n"
        '{"needs_clarification": true, "confidence": 0.75, '
        '"questions": [{"prompt": "Which year?", '
        '"options": [{"label": "2024", "value": "2024"}], '
        '"allow_free_text": true}]}\n```'
    )
    fake_llm = MagicMock()
    fake_llm.generate_structured = AsyncMock(side_effect=StructuredParseError("bad"))
    fake_llm.generate = AsyncMock(return_value=LLMResult(text=fenced, usage=Usage()))
    monkeypatch.setattr("taxflow.providers.get_llm", lambda: fake_llm)

    result = await ClarifyAgent().run("q?", STRONG_SIGNALS)
    assert result["needs_clarification"] is True
    assert result["questions"][0]["prompt"] == "Which year?"


# --- build_effective_question ------------------------------------------------


def test_build_effective_question_unchanged_without_clarifications():
    q = "How is CGT calculated?"
    assert build_effective_question(q, None) == q
    assert build_effective_question(q, []) == q


def test_build_effective_question_folds_answers():
    q = "How is CGT calculated?"
    clar = [{"prompt": "Which asset?", "value": "shares"}]
    result = build_effective_question(q, clar)
    assert result.startswith(q)
    assert "Clarifications provided by the user:" in result
    assert "- Which asset?: shares" in result


def test_build_effective_question_joins_multi_select_and_skips_empty():
    q = "Q?"
    clar = [
        {"prompt": "Types?", "value": ["a", "b"]},
        {"prompt": "Empty", "value": ""},
    ]
    result = build_effective_question(q, clar)
    assert "- Types?: a, b" in result
    assert "Empty" not in result
