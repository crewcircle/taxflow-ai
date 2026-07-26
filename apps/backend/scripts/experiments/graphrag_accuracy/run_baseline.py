"""Step 2: run the EXISTING, unmodified ResearchAgent against all 30
accuracy-suite questions - this is the number every other pipeline is compared
against. Same call the real accuracy suite makes; kept separate here (rather
than just re-running pytest) so its output lands in results/baseline.json in
the same shape run_lightrag.py / run_cognee.py produce.

Run: doppler run --project taxflow --config dev -- \\
     uv run python scripts/experiments/graphrag_accuracy/run_baseline.py
"""
from __future__ import annotations

import asyncio
import time

from common import load_questions, save_results

from taxflow.services.agents.research import ResearchAgent


async def main() -> None:
    questions = load_questions()
    agent = ResearchAgent()
    results = []

    for q in questions:
        print(f"[{q['id']}] {q['question'][:70]}...")
        start = time.monotonic()
        result = await agent.run(question=q["question"], client_id="experiment-baseline")
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

    save_results("baseline", results)


if __name__ == "__main__":
    asyncio.run(main())
