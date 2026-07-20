# Eval harness (Workstream B)

Separates the three failure modes of the research pipeline — **retrieval**,
**generation**, and **citation validity** — and lets us A/B a model swap on
**quality-per-dollar**.

Two tiers of tests live here:

| Kind | Command | Cost |
|---|---|---|
| Offline harness unit tests | `uv run pytest tests/eval -q` | free, no LLM/DB/network |
| Paid end-to-end runner | `uv run pytest tests/eval/ -v -s -m eval` | **real** Anthropic + OpenAI + DB |

Every backend command needs the `uv` PATH prefix:

```bash
cd apps/backend
export PATH="$HOME/.local/bin:$PATH"
```

## Offline tests (CI-safe, default)

```bash
uv run pytest tests/eval -q
```

`test_metrics.py`, `test_citations.py`, `test_judge.py`, `test_scoring.py`,
`test_cost.py`, `test_regression.py` are pure and offline: the judge test injects
a `MagicMock` LLM, everything else is deterministic arithmetic over fixtures.
They run in the normal suite (`uv run pytest tests/ -q`) with `eval` + `accuracy`
deselected.

## Paid end-to-end runner (manual only — never in CI/sandbox)

```bash
uv run pytest tests/eval/ -v -s -m eval
```

`test_eval_pipeline.py` is marked `pytest.mark.eval` and is **deselected by
default** via `addopts = -m 'not accuracy and not eval'` in `pyproject.toml`, so
it never runs in CI or the sandbox. For each gold question it:

1. runs retrieval (`retrieval.generate_candidates`, DB, no LLM) → `recall@k` /
   `mrr` / `ndcg@k` vs `expected_citations`;
2. runs one `ResearchAgent().run(...)` → judges the answer with `EvalJudge`;
3. checks citation validity against the rendered source list;
4. computes cost + latency, aggregates, writes the run, and diffs against the
   baseline.

It is **report-only by default** — it prints a per-topic / per-tier +
quality-per-dollar summary and a regression diff, but does not fail the build.
Set `EVAL_GATE_ON_REGRESSION=1` to turn the regression diff into a hard
assertion.

The per-question loop + aggregate + `write_run` + baseline-diff live in
`taxflow.services.eval.runner.run_eval_pipeline` (Task 1a); the test is now a
thin caller of it. `run_eval_pipeline` returns
`{"aggregate", "per_question", "diff", "record"}` and **never asserts on
regressions** — gating is the caller's decision.

## CLI: `scripts/run_eval.py` (eval-on-demand)

The same pipeline runs from a script (and the `taxflow-eval` console script)
without pytest:

```bash
cd apps/backend
export PATH="$HOME/.local/bin:$PATH"
uv run python scripts/run_eval.py --gate            # PAID: real Anthropic/OpenAI/DB
```

Flags:

| Flag | Default | Effect |
|---|---|---|
| `--questions` | `tests/eval/questions.json` | gold questions JSON |
| `--k` | `settings.EVAL_RECALL_K` | recall@k cutoff |
| `--output-dir` | `tests/eval/results` | runs.jsonl / latest.json / baseline.json |
| `--gate` | off | exit non-zero when `diff["has_regressions"]` |
| `--promote-baseline` | off | copy `latest.json` → `baseline.json` after a **clean** run only (refuses + exits non-zero if the run has regressions, regardless of `--gate`) |

`--gate` **replaces** the `EVAL_GATE_ON_REGRESSION` env toggle for the CLI /
workflow path (the pytest test still honours `EVAL_GATE_ON_REGRESSION=1`).

## CI: `.github/workflows/eval.yml`

A dedicated workflow (repo root) runs the paid eval — **never** the normal CI
suite. Triggers:

- **nightly `schedule`** (03:00 UTC) — always passes `--gate`, never
  `--promote-baseline`;
- **`workflow_dispatch`** — boolean inputs `gate` and `promote_baseline` map
  onto `--gate` / `--promote-baseline`.

It runs against a `pgvector/pgvector:pg16` service with real
`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `DATABASE_URL` secrets, uploads
`runs.jsonl` + `latest.json` as an artifact, and — only on an explicit dispatch
that requested promotion — commits `baseline.json` back to `main` (the CI
workspace is ephemeral, so the promoted baseline must be persisted).

**Droplet caveat:** the paid eval never runs on the deployed backend —
`scripts/deploy_backend.sh` rsyncs with `--exclude 'tests'`, so `tests/eval`
(and this runner's test entrypoint) is never shipped to prod. The workflow is
the only place the paid eval executes.

## Cost accounting: production vs judge overhead

`quality_per_dollar` measures the **production pipeline only** — the
`ResearchAgent.run()` tokens a real user query would incur. The **judge's own
tokens are eval overhead** and are tracked in a separate `judge_cost` field, and
are **excluded** from the production quality-per-dollar figure. This keeps the
A/B model-swap comparison honest: we compare what production would cost, not the
cost of grading it.

## Gold set

`questions.json` is the curated, citation-level gold set (seeded from the 30
accuracy questions). Each entry keeps `expected_topics` / `expected_citations`
for back-compat and adds a per-question `category` (topic tag) plus an optional
`relevant_citation_grades` map for graded nDCG.

## Baseline & A/B model comparison

`results/baseline.json` is the reference aggregate the runner diffs against
(seeded as an empty placeholder). To promote a good run to the baseline:

```bash
# after a paid run, results/latest.json holds the most recent record
cp tests/eval/results/latest.json tests/eval/results/baseline.json
```

To A/B a model swap, change `EVAL_JUDGE_TIER` / the `MODEL_TIER_MAP` (Workstream
A) or the tiers the pipeline routes to, run the paid eval, and compare
`quality_per_dollar` per tier in the printed `by_model_used` roll-up against the
baseline. `results/runs.jsonl` retains every run for longitudinal comparison.
