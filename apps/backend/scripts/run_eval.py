"""CLI entrypoint for the eval-on-demand pipeline (Task 1a).

Thin wrapper that delegates to ``taxflow.services.eval.runner.main`` so the
same code path runs from a script, the ``taxflow-eval`` console script, and the
``eval.yml`` GitHub workflow.

WARNING: this makes REAL Anthropic + OpenAI + DB calls (PAID). It is invoked
only by the dedicated eval workflow (nightly / manual dispatch) or manual local
runs — NEVER in CI against the sandbox or on the droplet (``deploy_backend.sh``
excludes ``tests/``).

Run manually::

    cd apps/backend
    export PATH="$HOME/.local/bin:$PATH"
    uv run python scripts/run_eval.py --gate

Flags mirror ``runner.main``:

    --questions        gold questions JSON (default: tests/eval/questions.json)
    --k                recall@k cutoff (default: settings.EVAL_RECALL_K)
    --output-dir       results dir (default: tests/eval/results)
    --gate             exit non-zero when diff["has_regressions"]
    --promote-baseline copy latest.json -> baseline.json after a clean run
"""

from __future__ import annotations

import sys

from taxflow.services.eval.runner import main

if __name__ == "__main__":
    sys.exit(main())
