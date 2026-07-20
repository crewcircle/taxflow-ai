"""Task 1b/1c: per-query observability — citation-validity, dollar cost, model_id.

Covers the pure eval helpers (``run_cost`` / ``check_citation_validity``) on
valid + fabricated-marker cases, the router persistence of the migration-035
observability columns for a live generation, a cache-hit row (cost 0 / NULL
validity / NULL model_id), the corrective (Sonnet) meta pricing, and that the
graph generate node + research corrective pass expose a CONCRETE resolved
model_id (a runtime ``resolve_model`` value, never a literal).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from taxflow import providers
from taxflow.config import settings
from taxflow.routers import query as query_mod
from taxflow.services.eval.citations import check_citation_validity
from taxflow.services.eval.cost import run_cost


# --- run_cost ----------------------------------------------------------------


def test_run_cost_haiku_prices_all_counters():
    pricing = settings.EVAL_MODEL_PRICING["haiku"]
    cost = run_cost("haiku", 1_000_000, 1_000_000, cache_read=1_000_000, cache_creation=1_000_000)
    expected = (
        pricing["input"] + pricing["output"] + pricing["cache_read"] + pricing["cache_creation"]
    )
    assert cost == pytest.approx(expected)


def test_run_cost_sonnet_more_expensive_than_haiku():
    assert run_cost("sonnet", 1000, 1000) > run_cost("haiku", 1000, 1000)


def test_run_cost_unknown_tier_is_zero():
    # 'cache' is not a priced tier → 0.0 (never blows up on a cache-hit row).
    assert run_cost("cache", 100, 100) == 0.0


# --- check_citation_validity -------------------------------------------------


def _result(answer: str, n_rendered: int) -> dict:
    rendered = [{"citation": f"c{i}"} for i in range(1, n_rendered + 1)]
    return {
        "answer": answer,
        "citations": [{"citation": f"c{i}"} for i in range(1, n_rendered + 1)],
        "trace": {"retrieval": {"rendered_sources": rendered}},
    }


def test_check_citation_validity_valid_answer():
    out = check_citation_validity(_result("Answer [1][2]", 3))
    assert out["valid"] is True
    assert out["fabricated_markers"] == []
    assert out["unmatched_citations"] == []
    assert out["total_citations"] == 2


def test_check_citation_validity_flags_fabricated_marker():
    # [5] is outside 1..3 rendered sources → fabricated.
    out = check_citation_validity(_result("Answer [1][5]", 3))
    assert out["valid"] is False
    assert 5 in out["fabricated_markers"]


# --- _observability_fields (router helper) -----------------------------------


def test_observability_fields_valid_answer():
    meta = {
        "model_used": "haiku",
        "input_tokens": 1000,
        "output_tokens": 500,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    trace = {"retrieval": {"rendered_sources": [{"citation": "c1"}, {"citation": "c2"}]}}
    fields = query_mod._observability_fields(
        "Answer [1][2]", [{"citation": "c1"}, {"citation": "c2"}], trace, meta
    )
    assert fields["citation_valid"] is True
    assert fields["invalid_citations"] is None
    assert fields["cost_usd"] == pytest.approx(run_cost("haiku", 1000, 500))


def test_observability_fields_fabricated_marker_stored():
    meta = {"model_used": "sonnet", "input_tokens": None, "output_tokens": None}
    trace = {"retrieval": {"rendered_sources": [{"citation": "c1"}]}}
    fields = query_mod._observability_fields("Answer [1][9]", [], trace, meta)
    assert fields["citation_valid"] is False
    assert fields["invalid_citations"]["fabricated_markers"] == [9]
    # None token counters coerce to 0 → cost 0, not a crash.
    assert fields["cost_usd"] == 0.0


def test_observability_fields_prices_corrective_sonnet_meta():
    """The corrective pass meta (Sonnet tier) is priced with Sonnet rates."""
    meta = {
        "model_used": "sonnet",
        "input_tokens": 2000,
        "output_tokens": 800,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    trace = {"retrieval": {"rendered_sources": [{"citation": "c1"}]}}
    fields = query_mod._observability_fields("Corrected [1]", [{"citation": "c1"}], trace, meta)
    assert fields["cost_usd"] == pytest.approx(run_cost("sonnet", 2000, 800))
    # Sonnet pricing must exceed the same tokens priced as Haiku.
    assert fields["cost_usd"] > run_cost("haiku", 2000, 800)


# --- cache-hit persistence ---------------------------------------------------


def test_persist_cached_query_zero_cost_null_validity_and_model_id():
    inserted: dict = {}

    class _Queries:
        def insert(self, row):
            inserted.update(row)
            return {"id": "qid"}

    db = MagicMock()
    db.queries = _Queries()
    client = {"id": "cid", "email": "e@example.com"}
    cached = {"answer": "A", "citations": [], "confidence": 0.9}

    qid = query_mod._persist_cached_query(db, client, "q?", "research", cached, 0.0)

    assert qid == "qid"
    assert inserted["model_used"] == "cache"
    assert inserted["cost_usd"] == 0
    # validity + model_id are left NULL (not measured for a cache hit).
    assert "citation_valid" not in inserted
    assert "invalid_citations" not in inserted
    assert "model_id" not in inserted


# --- model_id exposure: graph generate + research corrective -----------------


async def test_generate_node_exposes_concrete_model_id(monkeypatch):
    """The graph generate node returns a concrete resolved model_id matching
    providers.resolve_model(routed_tier) — a runtime value, not a literal."""
    from taxflow.ports.llm import LLMResult, Usage
    from taxflow.services.agents import graph as graph_mod

    fake_llm = MagicMock()
    fake_llm.generate = AsyncMock(
        return_value=LLMResult(text="Answer [1]", usage=Usage(input_tokens=10, output_tokens=5))
    )
    monkeypatch.setattr(graph_mod.research_agent, "_llm", fake_llm)
    monkeypatch.setattr(
        graph_mod.research_agent,
        "_increment_firm_usage",
        AsyncMock(return_value=None),
    )

    state = {
        "chunks": [{"id": "1", "citation": "c1", "content": "x", "source_url": "", "score": 0.5}],
        "question": "q",
        "routed_tier": "haiku",
        "client_id": "cid",
        "streaming": False,
    }
    out = await graph_mod.generate(state)
    assert out["model_id"] == providers.resolve_model("haiku")
    assert out["model_id"] != "haiku"  # concrete id, not the abstract tier


async def test_research_corrective_captures_sonnet_model_id(monkeypatch):
    """regenerate_with_feedback surfaces the concrete Sonnet model id in its
    result so corrected_meta carries it (previously discarded)."""
    from taxflow.services.agents import research as research_mod

    agent = research_mod.ResearchAgent()
    monkeypatch.setattr(
        agent,
        "_prepare",
        AsyncMock(return_value=("ctx", "", [{"citation": "c1"}], {}, None, 0, {})),
    )
    monkeypatch.setattr(
        agent,
        "_generate",
        AsyncMock(return_value=("Corrected [1]", {"input_tokens": 1, "output_tokens": 1})),
    )
    monkeypatch.setattr(agent, "_parse_citations", lambda a, m: [{"citation": "c1"}])
    monkeypatch.setattr(agent, "_estimate_confidence", lambda a, c, ci: 0.9)
    monkeypatch.setattr(agent, "_assemble_answer_trace", AsyncMock(return_value={}))

    result = await agent.regenerate_with_feedback("q", "cid", issues=[])
    assert result["model_used"] == "sonnet"
    assert result["model_id"] == providers.resolve_model("sonnet")
    assert result["model_id"] != "sonnet"


def test_router_persists_model_id_from_final_state():
    """The POST update dict carries model_id straight from final state's
    resolved model_id (falls into meta when no corrective pass ran)."""
    final = {
        "confidence": 0.9,
        "routed_tier": "haiku",
        "model_id": providers.resolve_model("haiku"),
        "input_tokens": 10,
        "output_tokens": 5,
    }
    corrected_meta = final.get("corrected_meta")
    meta = corrected_meta or {
        "confidence": final["confidence"],
        "model_used": final["routed_tier"],
        "model_id": final.get("model_id"),
        "input_tokens": final.get("input_tokens"),
        "output_tokens": final.get("output_tokens"),
    }
    assert meta["model_id"] == providers.resolve_model("haiku")
