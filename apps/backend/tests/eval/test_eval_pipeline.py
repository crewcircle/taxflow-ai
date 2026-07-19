"""End-to-end PAID eval runner (Task B4).

Marked ``pytest.mark.eval`` so it is DESELECTED by default (``addopts =
-m 'not accuracy and not eval'``) exactly like the accuracy suite. It makes REAL
Anthropic + OpenAI + DB calls and MUST NOT run in CI / the sandbox.

Run manually::

    cd apps/backend
    export PATH="$HOME/.local/bin:$PATH"
    uv run pytest tests/eval/ -v -s -m eval

Report-only by default: it prints a per-topic / per-tier + quality-per-dollar
summary and a regression diff against ``results/baseline.json``, but does NOT
fail the build on a regression. Set ``EVAL_GATE_ON_REGRESSION=1`` to turn the
regression diff into a hard assertion (default off).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from taxflow.config import settings
from taxflow.services.agents.research import ResearchAgent
from taxflow.services.eval.citations import check_citation_validity
from taxflow.services.eval.cost import run_cost
from taxflow.services.eval.judge import EvalJudge
from taxflow.services.eval.metrics import mrr, ndcg_at_k, recall_at_k
from taxflow.services.eval.regression import (
    diff_against_baseline,
    load_baseline,
    write_run,
)
from taxflow.services.eval.scoring import aggregate
from taxflow.services.knowledge.retrieval import generate_candidates

EVAL_DIR = Path(__file__).parent
RESULTS_DIR = EVAL_DIR / "results"
QUESTIONS = json.loads((EVAL_DIR / "questions.json").read_text())


@pytest.mark.eval
@pytest.mark.asyncio
async def test_eval_pipeline_report_and_regression(monkeypatch):
    # Echo the exact rendered context run() generated from, so the judge grades
    # against the real sources the answer saw (source-type boosts, firm/engagement
    # merges, rerank/truncation, historical) — not a re-derived candidate list.
    monkeypatch.setattr(settings, "EVAL_CAPTURE_CONTEXT", True)

    judge = EvalJudge()
    agent = ResearchAgent()
    per_question: list[dict] = []

    for q in QUESTIONS:
        gold = set(q["expected_citations"])
        grades = q.get("relevant_citation_grades")
        k = settings.EVAL_RECALL_K

        # --- retrieval eval (DB, no LLM) -------------------------------------
        candidates = await generate_candidates(q["question"])
        retrieved = [c.get("citation", "") for c in candidates]
        recall = recall_at_k(retrieved, gold, k)
        rr = mrr(retrieved, gold)
        ndcg = ndcg_at_k(retrieved, gold, k, grades=grades)

        # --- generation (one ResearchAgent.run) ------------------------------
        start = time.monotonic()
        result = await agent.run(q["question"], client_id="eval")
        wall_time_ms = int((time.monotonic() - start) * 1000)

        # --- judge (eval overhead, separate cost) ----------------------------
        # Use the EXACT context the answer was generated from (eval_context),
        # falling back to the answer's own trace-derived context only if absent.
        retrieved_context = result.get("eval_context", "")
        verdict = await judge.score(
            question=q["question"],
            answer=result.get("answer", ""),
            retrieved_context=retrieved_context,
            citations=result.get("citations", []),
        )

        validity = check_citation_validity(result)

        # --- cost: production pipeline vs judge overhead ---------------------
        model_tier = result.get("model_used", "haiku")
        prod_cost = run_cost(
            model_tier,
            result.get("input_tokens", 0) or 0,
            result.get("output_tokens", 0) or 0,
            cache_read=result.get("cache_read_input_tokens", 0) or 0,
            cache_creation=result.get("cache_creation_input_tokens", 0) or 0,
        )
        # Judge cost is real eval overhead: price the judge's own token usage,
        # tracked separately and excluded from the production quality-per-dollar.
        judge_usage = verdict.get("judge_usage", {})
        judge_cost = run_cost(
            settings.EVAL_JUDGE_TIER,
            judge_usage.get("input_tokens", 0) or 0,
            judge_usage.get("output_tokens", 0) or 0,
        )

        per_question.append(
            {
                "id": q["id"],
                "category": q.get("category"),
                "model_used": model_tier,
                "recall_at_k": recall,
                "mrr": rr,
                "ndcg": ndcg,
                "faithfulness": verdict.get("faithfulness", 0),
                "relevance": verdict.get("relevance", 0),
                "citation_correctness": verdict.get("citation_correctness", 0),
                "hallucination": bool(verdict.get("hallucination")),
                "citation_valid": validity["valid"],
                "cost": prod_cost,
                "judge_cost": judge_cost,
                "latency_ms": wall_time_ms,
            }
        )

    agg = aggregate(per_question)
    record = {
        "timestamp": time.time(),
        "judge_tier": settings.EVAL_JUDGE_TIER,
        "aggregate": agg,
        "per_question": per_question,
    }
    write_run(record, RESULTS_DIR)

    baseline = load_baseline(RESULTS_DIR)
    diff = diff_against_baseline(
        agg, baseline.get("aggregate", baseline), settings.EVAL_REGRESSION_TOLERANCE
    )

    print("\n=== Eval summary (production pipeline; judge cost is eval overhead) ===")
    print(json.dumps(agg["overall"], indent=2))
    print("--- by category ---")
    print(json.dumps(agg["by_category"], indent=2))
    print("--- by model_used (tier) ---")
    print(json.dumps(agg["by_model_used"], indent=2))
    print("--- regression diff vs baseline ---")
    print(json.dumps(diff, indent=2))

    if os.getenv("EVAL_GATE_ON_REGRESSION") == "1":
        assert not diff["has_regressions"], (
            "Eval regression beyond tolerance: "
            + json.dumps(diff["overall"]["regressions"])
        )
