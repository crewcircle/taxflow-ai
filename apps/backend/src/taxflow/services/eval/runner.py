"""Eval-on-demand pipeline runner (Task 1a).

Extracts the per-question loop + aggregate + ``write_run`` + baseline-diff that
used to live inline in ``tests/eval/test_eval_pipeline.py`` into a reusable
:func:`run_eval_pipeline` coroutine, plus a thin :func:`main` argparse wrapper so
the same pipeline can run from a script / CLI / CI workflow.

This makes **real** Anthropic + OpenAI + DB calls (one ``ResearchAgent.run`` and
one ``EvalJudge.score`` per question, plus DB retrieval). It MUST NOT run in CI
against the sandbox or on the droplet — it is invoked only by the dedicated
``eval.yml`` workflow (nightly / manual dispatch) and by manual local runs.

**Gating is the caller's decision.** :func:`run_eval_pipeline` returns the
baseline ``diff`` (including ``has_regressions``) but never asserts on it; the
CLI / test decides whether a regression should fail the run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import time
from pathlib import Path

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

DEFAULT_QUESTIONS = Path(__file__).resolve().parents[4] / "tests" / "eval" / "questions.json"
DEFAULT_RESULTS_DIR = Path(__file__).resolve().parents[4] / "tests" / "eval" / "results"


async def run_eval_pipeline(
    questions: list[dict],
    *,
    k: int,
    results_dir: str | Path,
    capture_context: bool = True,
) -> dict:
    """Run the full eval pipeline over ``questions`` and return the results.

    For each gold question this runs retrieval (DB, no LLM) → ``recall@k`` /
    ``mrr`` / ``ndcg@k``, one ``ResearchAgent.run`` (production generation),
    one ``EvalJudge.score`` (eval overhead), citation validity, and cost +
    latency. Records are aggregated, the run is appended to ``runs.jsonl`` /
    ``latest.json``, and the aggregate is diffed against ``baseline.json``.

    Returns ``{"aggregate", "per_question", "diff", "record"}``. The ``diff``
    carries ``has_regressions`` but this function never asserts on it — gating
    is the caller's decision.
    """
    # Echo the exact rendered context run() generated from, so the judge grades
    # against the real sources the answer saw (source-type boosts, firm/engagement
    # merges, rerank/truncation, historical) — not a re-derived candidate list.
    settings.EVAL_CAPTURE_CONTEXT = capture_context

    judge = EvalJudge()
    agent = ResearchAgent()
    per_question: list[dict] = []

    for q in questions:
        gold = set(q["expected_citations"])
        grades = q.get("relevant_citation_grades")

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
    write_run(record, results_dir)

    baseline = load_baseline(results_dir)
    diff = diff_against_baseline(
        agg, baseline.get("aggregate", baseline), settings.EVAL_REGRESSION_TOLERANCE
    )

    return {
        "aggregate": agg,
        "per_question": per_question,
        "diff": diff,
        "record": record,
    }


def _print_summary(agg: dict, diff: dict) -> None:
    print("\n=== Eval summary (production pipeline; judge cost is eval overhead) ===")
    print(json.dumps(agg["overall"], indent=2))
    print("--- by category ---")
    print(json.dumps(agg["by_category"], indent=2))
    print("--- by model_used (tier) ---")
    print(json.dumps(agg["by_model_used"], indent=2))
    print("--- regression diff vs baseline ---")
    print(json.dumps(diff, indent=2))


def main(argv: list[str] | None = None) -> int:
    """Thin argparse wrapper around :func:`run_eval_pipeline`.

    Runs the PAID eval pipeline once, prints the summary + baseline diff, and
    optionally gates on regressions / promotes a clean run to the baseline.
    Returns a process exit code (0 = ok, 1 = gated regression).
    """
    parser = argparse.ArgumentParser(
        prog="taxflow-eval",
        description="Run the TaxFlow eval pipeline (PAID: real Anthropic/OpenAI/DB calls).",
    )
    parser.add_argument(
        "--questions",
        type=Path,
        default=DEFAULT_QUESTIONS,
        help="Path to the gold questions JSON (default: tests/eval/questions.json).",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=settings.EVAL_RECALL_K,
        help="Recall@k cutoff (default: settings.EVAL_RECALL_K).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_RESULTS_DIR,
        help="Directory for runs.jsonl / latest.json / baseline.json (default: tests/eval/results).",
    )
    parser.add_argument(
        "--gate",
        action="store_true",
        help="Exit non-zero when the baseline diff reports has_regressions "
        "(replaces the EVAL_GATE_ON_REGRESSION env toggle).",
    )
    parser.add_argument(
        "--promote-baseline",
        action="store_true",
        help="After a clean run (no gated regressions), copy latest.json -> baseline.json.",
    )
    args = parser.parse_args(argv)

    questions = json.loads(Path(args.questions).read_text())
    outcome = asyncio.run(
        run_eval_pipeline(
            questions,
            k=args.k,
            results_dir=args.output_dir,
            capture_context=True,
        )
    )
    agg = outcome["aggregate"]
    diff = outcome["diff"]
    _print_summary(agg, diff)

    has_regressions = bool(diff["has_regressions"])
    if args.gate and has_regressions:
        print(
            "\nEval regression beyond tolerance: "
            + json.dumps(diff["overall"]["regressions"])
        )
        return 1

    if args.promote_baseline:
        results_dir = Path(args.output_dir)
        latest = results_dir / "latest.json"
        baseline = results_dir / "baseline.json"
        shutil.copyfile(latest, baseline)
        print(f"\nPromoted {latest} -> {baseline}")

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
