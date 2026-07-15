"""Tests for verify gating (Task B2) + hardened parsing / corrective pass (C3)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from taxflow.config import settings
from taxflow.services.agents import verify as verify_mod
from taxflow.services.agents.verify import VerifyAgent


# --- Task B2: gate fires only on risky answers, defaults to Haiku -------------


def test_should_verify_skips_confident_well_cited(monkeypatch):
    monkeypatch.setattr(settings, "VERIFY_CONFIDENCE_THRESHOLD", 0.60)
    monkeypatch.setattr(settings, "VERIFY_MIN_CITATIONS", 1)
    citations = [{"citation": "ITAA 1997 s.8-1"}]
    assert verify_mod.should_verify(0.9, citations, "A well cited answer [1]") is False


def test_should_verify_fires_on_low_confidence(monkeypatch):
    monkeypatch.setattr(settings, "VERIFY_CONFIDENCE_THRESHOLD", 0.60)
    assert verify_mod.should_verify(0.3, [{"citation": "x"}], "answer [1]") is True


def test_should_verify_fires_on_no_citations(monkeypatch):
    monkeypatch.setattr(settings, "VERIFY_MIN_CITATIONS", 1)
    assert verify_mod.should_verify(0.9, [], "answer with no citations") is True


def test_should_verify_fires_on_insufficient_phrase():
    ans = "The provided sources do not contain sufficient information to answer."
    assert verify_mod.should_verify(0.9, [{"citation": "x"}], ans) is True


def test_verify_model_defaults_to_haiku(monkeypatch):
    monkeypatch.setattr(settings, "VERIFY_MODEL", "claude-haiku-4-5")
    # Low confidence but has citations and no insufficient phrase -> not severe.
    model = verify_mod.verify_model_for(0.3, [{"citation": "x"}], "answer [1]")
    assert model == "claude-haiku-4-5"


def test_verify_model_escalates_to_sonnet_when_severe(monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_SONNET_MODEL", "claude-sonnet-4-6")
    # No citations -> severe -> Sonnet.
    assert verify_mod.verify_model_for(0.3, [], "answer") == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_verify_run_uses_default_model(monkeypatch):
    monkeypatch.setattr(settings, "VERIFY_MODEL", "claude-haiku-4-5")
    agent = VerifyAgent()
    fake_response = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = '{"overall_status": "verified", "issues": []}'
    fake_response.content = [block]
    agent._client = MagicMock()
    agent._client.messages.create = AsyncMock(return_value=fake_response)

    await agent.run(draft="d", citations=[], question="q")
    assert agent._client.messages.create.await_args.kwargs["model"] == "claude-haiku-4-5"


# --- Task C3: hardened JSON parsing on fenced / malformed output --------------


def test_parse_plain_json():
    assert verify_mod._parse_verification('{"overall_status": "verified"}')["overall_status"] == "verified"


def test_parse_fenced_json():
    text = '```json\n{"overall_status": "needs_correction", "issues": []}\n```'
    assert verify_mod._parse_verification(text)["overall_status"] == "needs_correction"


def test_parse_json_with_surrounding_prose():
    text = 'Here is my review:\n{"overall_status": "unreliable", "issues": []}\nHope that helps.'
    assert verify_mod._parse_verification(text)["overall_status"] == "unreliable"


def test_parse_malformed_falls_back_to_parse_error():
    assert verify_mod._parse_verification("not json at all")["overall_status"] == "parse_error"


# --- Task C3: needs_correction detection --------------------------------------


def test_needs_correction_on_status():
    assert verify_mod.needs_correction({"overall_status": "needs_correction", "issues": []}) is True
    assert verify_mod.needs_correction({"overall_status": "unreliable", "issues": []}) is True


def test_needs_correction_on_critical_issue():
    v = {"overall_status": "verified", "issues": [{"severity": "critical", "issue": "wrong rate"}]}
    assert verify_mod.needs_correction(v) is True


def test_needs_correction_false_on_clean():
    v = {"overall_status": "verified", "issues": [{"severity": "note", "issue": "typo"}]}
    assert verify_mod.needs_correction(v) is False
    # parse_error is non-actionable.
    assert verify_mod.needs_correction({"overall_status": "parse_error", "issues": []}) is False


# --- Task C3: corrective pass bounded to ONE call -----------------------------


@pytest.mark.asyncio
async def test_maybe_verify_corrective_pass_runs_exactly_once(monkeypatch):
    import taxflow.routers.query as q

    monkeypatch.setattr(settings, "CORRECTIVE_PASS_ENABLED", True)

    verification = {"overall_status": "needs_correction", "issues": [{"claim": "c", "issue": "i"}]}
    with patch.object(q.verify_mod, "should_verify", return_value=True), patch.object(
        q.verify_mod, "verify_model_for", return_value="claude-haiku-4-5"
    ), patch.object(
        q.verifier, "run", new=AsyncMock(return_value=verification)
    ), patch.object(
        q.agent,
        "regenerate_with_feedback",
        new=AsyncMock(
            return_value={
                "answer": "Corrected [1]",
                "citations": [{"citation": "x"}],
                "confidence": 0.8,
                "model_used": "sonnet",
            }
        ),
    ) as mock_regen:
        answer, citations, verif, caveat = await q._maybe_verify(
            question="q", client_id="c", answer="bad", citations=[{"citation": "x"}], confidence=0.3
        )

    # Exactly ONE corrective regeneration — no loop.
    mock_regen.assert_awaited_once()
    assert answer == "Corrected [1]"
    assert caveat is not None
    assert verif["corrective_pass"] is True


@pytest.mark.asyncio
async def test_maybe_verify_skips_when_not_risky(monkeypatch):
    import taxflow.routers.query as q

    with patch.object(q.verify_mod, "should_verify", return_value=False), patch.object(
        q.verifier, "run", new=AsyncMock()
    ) as mock_run:
        answer, citations, verif, caveat = await q._maybe_verify(
            question="q", client_id="c", answer="good [1]", citations=[{"citation": "x"}], confidence=0.9
        )

    mock_run.assert_not_awaited()
    assert verif is None
    assert caveat is None
    assert answer == "good [1]"
