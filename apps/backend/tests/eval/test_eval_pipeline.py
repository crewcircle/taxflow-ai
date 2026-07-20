"""End-to-end PAID eval runner (Task B4).

Marked ``pytest.mark.eval`` so it is DESELECTED by default (``addopts =
-m 'not accuracy and not eval'``) exactly like the accuracy suite. It makes REAL
Anthropic + OpenAI + DB calls and MUST NOT run in CI / the sandbox.

Run manually::

    cd apps/backend
    export PATH="$HOME/.local/bin:$PATH"
    uv run pytest tests/eval/ -v -s -m eval

The per-question loop + aggregate + ``write_run`` + baseline-diff now live in
``taxflow.services.eval.runner.run_eval_pipeline`` (Task 1a) so the same
pipeline runs from the CLI / ``eval.yml`` workflow. This test is a thin caller:
it runs the pipeline report-only, prints the summary + regression diff, and does
NOT fail the build on a regression. Set ``EVAL_GATE_ON_REGRESSION=1`` to turn the
regression diff into a hard assertion (default off).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from taxflow.config import settings
from taxflow.services.eval import runner

EVAL_DIR = Path(__file__).parent
RESULTS_DIR = EVAL_DIR / "results"
QUESTIONS = json.loads((EVAL_DIR / "questions.json").read_text())


@pytest.mark.eval
@pytest.mark.asyncio
async def test_eval_pipeline_report_and_regression():
    outcome = await runner.run_eval_pipeline(
        QUESTIONS,
        k=settings.EVAL_RECALL_K,
        results_dir=RESULTS_DIR,
        capture_context=True,
    )
    agg = outcome["aggregate"]
    diff = outcome["diff"]

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
