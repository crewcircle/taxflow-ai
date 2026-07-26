"""Validation step BEFORE touching production model config: run the REAL,
unmodified ResearchAgent code path against the real knowledge base, but with
every model tier redirected to DeepSeek V4 Flash via OpenRouter instead of
Claude - so we get a real accuracy-suite score for "would DeepSeek be good
enough for the main app" before spending any engineering time wiring it into
settings.py/doppler for production.

Overrides three settings in-process only (this script's own process, never
the deployed app), BEFORE ResearchAgent/get_llm() is ever touched (get_llm()
is @lru_cache'd, so the override must land before its first call):
  - `settings.MODEL_TIER_MAP` - routes every tier to the DeepSeek model string
    (`providers.resolve_model()` checks this map before the legacy
    ANTHROPIC_*_MODEL fields).
  - `settings.LLM_API_KEY` / `settings.LLM_API_BASE` - the adapter
    (`providers.get_llm()`) otherwise always constructs itself with
    `api_key=settings.ANTHROPIC_API_KEY`, which it then sends to WHATEVER
    endpoint the model string points at - including OpenRouter, where an
    Anthropic key is not valid auth ("Missing Authentication header"). These
    two settings are the adapter's own designed override hook for exactly
    this ("LLM_API_KEY is the generic override that always wins" - see
    providers.py's get_llm() docstring/comment).

Requires OPENROUTER_API_KEY (same as run_lightrag.py / run_cognee.py).

Run: doppler run --project taxflow --config prd -- \\
     uv run python scripts/experiments/graphrag_accuracy/run_baseline_deepseek.py
"""
from __future__ import annotations

import asyncio
import os
import time

from common import save_results, load_questions

from taxflow.config import settings

DEEPSEEK_MODEL = "openrouter/deepseek/deepseek-v4-flash"


async def main() -> None:
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise RuntimeError(
            "OPENROUTER_API_KEY not set - run "
            "`doppler secrets set OPENROUTER_API_KEY --project taxflow --config dev` first."
        )

    # In-process only override - never touches settings.py, doppler, or the
    # deployed app. Must happen before ResearchAgent/get_llm() is imported and
    # instantiated below (get_llm() is @lru_cache'd - see module docstring).
    for tier in ("haiku", "sonnet", "draft", "verify", "rerank"):
        settings.MODEL_TIER_MAP[tier] = DEEPSEEK_MODEL
    settings.LLM_API_KEY = os.environ["OPENROUTER_API_KEY"]
    settings.LLM_API_BASE = "https://openrouter.ai/api/v1"
    print(f"Overrode MODEL_TIER_MAP -> {DEEPSEEK_MODEL}, LLM_API_KEY/LLM_API_BASE -> OpenRouter (this process only)")

    from taxflow.services.agents.research import ResearchAgent

    questions = load_questions()
    agent = ResearchAgent()
    results = []

    for q in questions:
        print(f"[{q['id']}] {q['question'][:70]}...")
        start = time.monotonic()
        result = await agent.run(question=q["question"], client_id="experiment-baseline-deepseek")
        elapsed_ms = (time.monotonic() - start) * 1000
        results.append(
            {
                "id": q["id"],
                "answer": result.get("answer", ""),
                "citations": result.get("citations", []),
                "wall_ms": round(elapsed_ms),
            }
        )
        print(f"  -> {elapsed_ms:.0f}ms, {len(result.get('citations', []))} citations")

    save_results("baseline_deepseek", results)


if __name__ == "__main__":
    asyncio.run(main())
