"""Same as run_baseline_deepseek.py, but drives the REAL production code path
(graph.py's research_graph, what routers/query.py actually calls) instead of
ResearchAgent.run() directly.

Why this exists: every other script in this experiment (and the real
tests/accuracy/ suite) calls ResearchAgent.run() directly, which never invokes
VerifyAgent at all. Production traffic goes through research_graph, which
internalises the gated verify pass and the at-most-once corrective pass
(graph.py's route_after_generate -> verify -> route_after_verify ->
corrective_generate). Fix 2 of the RAG-quality audit (VerifyAgent's
topic-mismatch gate) is specifically invisible to the plain ResearchAgent
path - this script exists to measure the score the real app actually
produces, not just the pre-verify draft.

Same DeepSeek-via-OpenRouter override as run_baseline_deepseek.py - see that
script's docstring for why LLM_API_KEY/LLM_API_BASE/MODEL_TIER_MAP must be set
before ANY of graph.py's module-level singletons (research_agent, verifier,
clarifier - all constructed at import time) are ever imported.

Run: doppler run --project taxflow --config prd -- \\
     uv run python scripts/experiments/graphrag_accuracy/run_baseline_deepseek_graph.py
"""
from __future__ import annotations

import asyncio
import os
import time

from common import save_results, load_questions

from taxflow.config import settings

DEEPSEEK_MODEL = "openrouter/deepseek/deepseek-v4-flash"
# Fixed placeholder UUID (real column type) rather than a bare string, so the
# firm-knowledge search's client_id lookup doesn't fail on every question.
EXPERIMENT_CLIENT_ID = "00000000-0000-0000-0000-000000000000"
# Distinct results filename per flag combination, so an A/B comparison run
# never silently overwrites a prior run's results.
_NAME_PARTS = ["baseline_deepseek_graph"]
if os.environ.get("USE_COHERE_RERANK"):
    _NAME_PARTS.append("cohere_rerank")
if os.environ.get("USE_QUERY_DECOMPOSITION"):
    _NAME_PARTS.append("query_decomp")
RESULTS_NAME = "_".join(_NAME_PARTS)


async def main() -> None:
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise RuntimeError(
            "OPENROUTER_API_KEY not set - run "
            "`doppler secrets set OPENROUTER_API_KEY --project taxflow --config dev` first."
        )

    # In-process only override - never touches settings.py, doppler, or the
    # deployed app. Must happen before graph.py (and its module-level
    # research_agent/verifier/clarifier singletons) is ever imported.
    for tier in ("haiku", "sonnet", "draft", "verify", "verify_strong", "rerank"):
        settings.MODEL_TIER_MAP[tier] = DEEPSEEK_MODEL
    settings.LLM_API_KEY = os.environ["OPENROUTER_API_KEY"]
    settings.LLM_API_BASE = "https://openrouter.ai/api/v1"
    print(f"Overrode MODEL_TIER_MAP -> {DEEPSEEK_MODEL}, LLM_API_KEY/LLM_API_BASE -> OpenRouter (this process only)")
    # RERANK_MODE="cohere" (RAG-quality audit precision follow-up #1), opt-in
    # via USE_COHERE_RERANK=1 so this script stays usable for both an A/B
    # baseline run and a reranked run. Reads settings.OPENROUTER_API_KEY
    # directly - a separate field from the LLM_API_KEY override above (that
    # one's for chat completions; the reranker hits a different endpoint).
    if os.environ.get("USE_COHERE_RERANK"):
        settings.RERANK_MODE = "cohere"
        settings.OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
        print("RERANK_MODE -> cohere")
    # QUERY_DECOMPOSITION_ENABLED (RAG-quality audit precision follow-up #3),
    # opt-in via USE_QUERY_DECOMPOSITION=1. decompose_query() resolves its
    # model via providers.resolve_model("rerank") - already overridden to
    # DeepSeek above, so this uses DeepSeek/OpenRouter automatically, not
    # Anthropic (whose credits are exhausted this session).
    if os.environ.get("USE_QUERY_DECOMPOSITION"):
        settings.QUERY_DECOMPOSITION_ENABLED = True
        print("QUERY_DECOMPOSITION_ENABLED -> True (via DeepSeek/OpenRouter)")

    from taxflow.services.agents.graph import research_graph

    questions = load_questions()
    results = []

    for q in questions:
        print(f"[{q['id']}] {q['question'][:70]}...")
        start = time.monotonic()
        initial_state = {
            "question": q["question"],
            "client": None,
            "client_id": EXPERIMENT_CLIENT_ID,
            "session_id": None,
            "client_ref": None,
            "embedding": None,
            "streaming": False,
            "corrective_count": 0,
            "re_retrieved": False,
            "clarifications": None,
        }
        try:
            # 400s: same rationale as run_baseline_deepseek.py, PLUS this path
            # can run a gated verify call and an at-most-once corrective
            # generate call on top of the draft generation - up to 3x one
            # slow OpenRouter/DeepSeek call in the worst case.
            final = await asyncio.wait_for(research_graph.ainvoke(initial_state), timeout=600)
        except Exception as e:  # noqa: BLE001 - one bad question must not kill the run
            elapsed_ms = (time.monotonic() - start) * 1000
            print(f"  -> FAILED after {elapsed_ms:.0f}ms: {e!r}")
            results.append({"id": q["id"], "answer": "", "citations": [], "wall_ms": round(elapsed_ms), "error": repr(e)})
            save_results(RESULTS_NAME, results)
            continue
        elapsed_ms = (time.monotonic() - start) * 1000
        verification = final.get("verification")
        results.append(
            {
                "id": q["id"],
                "answer": final.get("answer", ""),
                "citations": final.get("citations", []),
                "wall_ms": round(elapsed_ms),
                # Not scored, but worth keeping: did verify even run, and if so
                # what did it decide - this is the whole point of this script.
                "verify_ran": verification is not None,
                "verify_status": (verification or {}).get("overall_status"),
                "caveat": final.get("caveat"),
            }
        )
        print(
            f"  -> {elapsed_ms:.0f}ms, {len(final.get('citations', []))} citations, "
            f"verify_ran={verification is not None}, status={(verification or {}).get('overall_status')}"
        )
        save_results(RESULTS_NAME, results)


if __name__ == "__main__":
    asyncio.run(main())
