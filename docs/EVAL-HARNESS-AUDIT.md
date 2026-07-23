# TaxFlow Eval Harness Audit

Based on the [Vorflux Manifesto](https://vorflux.com/manifesto) ("The Great Flattening").
Every claim below is grounded in the actual code in `services/eval/`,
`tests/accuracy/`, `.github/workflows/eval.yml`, and `services/agents/`.

## What the current harness does

| Component | File | What it measures |
|---|---|---|
| Retrieval metrics | `eval/metrics.py` | recall@k, MRR, NDCG@k — deterministic, no LLM |
| LLM-as-judge | `eval/judge.py` | faithfulness, relevance, citation_correctness, hallucination (1–5 scales) |
| Citation validity | `eval/citations.py` | fabricated markers, unmatched citations — deterministic |
| Cost tracking | `eval/cost.py` | per-tier $ token → dollar arithmetic, quality-per-dollar |
| Aggregation | `eval/scoring.py` | overall + by_category + by_model_used roll-ups |
| Baseline diff | `eval/regression.py` | per-metric deltas vs baseline, regression flags, tolerance |
| Production drift | `eval/drift.py` | production metric snapshot diff (feedback rates, latency, cost) |
| Runner | `eval/runner.py` | orchestrates the full pipeline (retrieval → generation → judging → scoring → diff) |
| Accuracy suite | `tests/accuracy/test_research_accuracy.py` | 30 gold questions, heuristic 1–5 scoring against expected_topics + expected_citations |
| CI workflow | `.github/workflows/eval.yml` | nightly at 03:00 UTC + manual dispatch, regression gating, baseline promotion |
| Gold questions | `tests/eval/questions.json` | 30 questions across 21 Australian tax topics, each with expected_citations + relevant_citation_grades |
| Production drift | `eval/drift.py` + `production_quality_snapshots` table | scheduled drift detection against real production queries, not against gold questions |

What's strong about it: modular and deterministic where it can be (metrics, citations, cost, aggregation — zero LLM), LLM-only where it has to be (judge), wired through the same ports-and-adapters stack as production, and regression-gated nightly with baseline promotion on manual dispatch.

## Audit against manifesto principles

### 1. THE HARNESS IS JUDGMENT, CODIFIED

> *"The harness is the one place your engineering principles stop sitting in your head and start running on every session."*

**What's present:** The judge prompt encodes the definition of a good answer: groundedness, completeness, citation accuracy, hallucination flagging. The baseline diff encodes the quality bar ("nothing ships below this"). The accuracy suite has per-question expected topics and citations. The regression tolerance (`EVAL_REGRESSION_TOLERANCE`) encodes how much slack you allow.

**What's missing — the judgment that's still in your head:**

- **The model-swap decision.** When a new model drops (Claude Opus 4.8 → someone ships Opus 5.0), the question is: do we switch? The current harness gives you `quality_per_dollar` by model tier, which is the right data, but the *decision* — "switch if quality-per-dollar improves by ≥X% and hallucination_rate doesn't regress beyond Y" — is not encoded. That's a human making the same call every time.
- **The "good enough" threshold for each metric.** The baseline diff detects *regressions* (delta beyond tolerance), but what about absolute thresholds? If faithfulness drops from 4.2 to 3.8, the diff catches it. But if faithfulness was never above 3.0 to begin with — i.e., the baseline is already bad — nothing fires. The harness has no encoding of "faithfulness below 3.5 is unacceptable regardless of whether it's a regression."
- **Category-specific quality expectations.** A hallucination on a superannuation answer is worse than a hallucination on a trading_stock answer — the stakes are different. Currently the aggregation does `by_category` roll-ups, but the diff treats every category identically, with the same tolerance. The judgment of which topics are safety-critical is not encoded.

### 2. NEUTRALITY — ROUTE TO WHOEVER WINS

> *"The layer stays neutral: your judgment, run across every lab's best model, the work moving to whichever one wins a given job this week."*

**What's present:** `by_model_used` aggregation. `quality_per_dollar` per tier. `settings.EVAL_MODEL_PRICING` with per-tier rates — the cost accounting is honest about comparing production cost, not judge overhead.

**What's missing:**

- **Cross-model A/B on every eval run.** Currently the pipeline runs one `ResearchAgent.run` per question using whatever model tier the agent resolves (driven by the tier param, defaulting to the configured default). It does not systematically run the same question through multiple model tiers and compare. To say "Opus 4.8 beats Opus 4.5 on quality-per-dollar for CGT questions," you'd need to run both and diff them.
- **No model-swap gate in CI.** The eval workflow gates on regression *against baseline*, but it doesn't gate on "is the current default model still the best?" You can promote a baseline and still be using a suboptimal model.
- **Tier routing is hardcoded by name,** not by performance data. The `resolve_model` function maps tier strings like "sonnet" or "haiku" to concrete model IDs. If GPT-5.5 beats Claude on retrieval but Claude beats it on drafting, there's no mechanism to route a specific question *type* to a specific model based on eval data.

### 3. PROFILE THE BOTTLENECK, DROWN IT IN TOKENS

> *"Tune the setup to your own codebase and throw tokens at the parts of the lifecycle that keep tripping you up."*

**What's present:** The LLM judge is a textbook tokenmaxxing play — instead of a human reading every answer, an LLM grades it on 3 axes. The 30-question gold set with reference citations is another: the expected citations encode the knowledge that a human tax professional would check against. The nightly schedule means the harness runs without you in the room.

**What's missing:**

- **The bottleneck isn't the judge; it's the gating decision.** "Can I trust this merge?" is the real bottleneck — the same one the manifesto identifies. The harness runs nightly and detects regressions, but it doesn't feed that signal back into the deploy pipeline. On `main`, `deploy-backend` runs independently of the eval gate. A regression goes red in the nightly eval job, but the deploy that caused it already shipped hours ago.
- **Eval doesn't run on PRs.** It's nightly + manual dispatch. The manifesto says "the bottleneck moves up to: whether you can trust a merge you didn't read line by line." Your current workflow requires you to trust the merge *then* find out the next day. An eval-on-PR pattern (running against an ephemeral DB with the same gold questions) would shift that gate to pre-merge.
- **The accuracy suite is heuristic, not judged.** `test_research_accuracy.py` uses a simple topic/citation overlap heuristic (keyword matching against expected_topics and expected_citations), not the LLM judge. That's faster and cheaper, but it means the accuracy suite and the eval pipeline use *different quality definitions*. A heuristic pass doesn't guarantee a judge pass, and vice versa. The bottleneck is that you can't trust the accuracy suite's signal.
- **No targeted re-eval of failing questions.** If question #14 (GST) fails tonight, the harness reports it. But there's no mechanism to re-run *just* the failing question subset at higher cost (e.g., multiple judge passes, a more expensive judge model, or with different retrieval parameters) to determine whether the failure is real or noise.

### 4. OUT OF THE LOOP — THE HARNESS CHECKS ITS OWN OUTPUT

> *"You used to babysit the session. Now you babysit the system: whether you can trust a merge."*

**What's present:** Nightly unattended runs, regression gating, artifact uploads for post-hoc inspection. The production drift snapshot captures real-world signal (feedback rates, verification failures, latency) against the same baseline diff engine.

**What's missing:**

- **No deploy guard.** The deploy script (`deploy_backend.sh`) has a health smoke test and a rollback — that's good. But it doesn't consult the eval baseline. A model config change that silently degrades retrieval quality passes the health check and ships; the eval catches it hours later. The deploy gate should ideally have a fast eval pass (even a subset: top-5 highest-stakes questions, judged quickly) before going live.
- **No canary deploy.** The manifest describes "twenty autonomous sessions hitting one codebase without trampling each other." Your harness detects problems in aggregate, after the fact. A canary pattern — deploy to a small fraction of traffic, run eval against those answers, compare to baseline, promote or rollback — would shift the gate to before the full deploy completes.
- **Drift detection is recorded but not acted on.** `production_quality_snapshots` captures drift. But there's no automated action — it doesn't page anyone, it doesn't halt the scheduler, it doesn't force a rollback. A real production drift (e.g., a model provider silently changed their API behavior) would sit in the database until someone reads it.

### 5. SELF-PROFILING — WHAT DECISION FRAMEWORK IS IN YOUR HEAD?

> *"Everyone's real work becomes self-profiling: what decision-making framework is in your head that isn't in the codebase."*

**What's present:** The judge prompt encodes partial judgment. The gold questions encode what a human tax professional would check. The baseline encodes what "normal" looks like.

**What's missing — the framework that's still in your head:**

- **What makes a question "hard"?** The 30 questions span 21 categories, but there's no difficulty tiering encoded. Some questions genuinely have ambiguous answers under Australian tax law (e.g., PSI vs. personal services business determinations). The harness treats them all identically. Your judgment about which questions are inherently subjective and should have wider tolerances is not encoded.
- **When is a regression actually a regression vs. model improvement?** The LLM judge uses the same model family as the generation (Anthropic). If a new model release makes *both* the generation and the judge better, the judge might flag "hallucination" on claims that are actually correct but phrased in a way the old judge doesn't recognize. The harness has no cross-model judge inter-rater reliability check.
- **What's the actual user-facing quality signal?** The harness measures faithfulness, relevance, citation_correctness, and hallucination — these are proxy metrics for "would a tax professional trust this?" But the ultimate signal is user behavior: feedback (thumbs up/down), whether they save the answer as a document, whether they re-ask the same question. The production drift snapshot captures `feedback_down_rate`, but the eval pipeline doesn't correlate judge scores with real user feedback to validate that the judge's definition of "good" matches what users actually find good.

## Prioritized improvements

### Priority 1 — Pre-merge eval gate (the bottleneck shift)

The single highest-impact change from the manifesto: move eval from post-deploy to pre-merge.

- **What to build:** A `test-backend-eval` job in `ci.yml` that runs on PRs. It runs a *subset* of the eval pipeline (fast: retrieval metrics only, or a smaller question set, or the heuristic accuracy suite with the judge) against the PR's code. If it regresses beyond tolerance, the PR goes red.
- **Why it matters:** The manifesto's bottleneck is "can I trust this merge?" Currently you can't — you find out the next morning. Shifting the gate left means you never merge a regression.
- **Tradeoff:** Cost and time. The full eval pipeline makes 30+ real LLM calls. A PR eval would need to be cheaper. Options: (a) retrieval-only (no generation, no judge — metrics alone catch schema drift and retrieval degradation), (b) a 5-question "smoke" subset of the highest-stakes topics, (c) the heuristic accuracy suite (topic/citation overlap, no LLM judge).

### Priority 2 — Cross-model A/B runner

Codify the model-swap decision so you're not making the same call by hand every release.

- **What to build:** A `--compare-models` flag on the eval runner that runs the same question set through multiple tiers and diffs them. Output: per-category "Opus 4.8 beats Opus 4.5 on quality-per-dollar in 14/21 categories; loses in 3; ties in 4."
- **Why it matters:** Manifesto principle 2 (neutrality) — the harness should route to whoever wins. Currently you'd have to run the pipeline manually with different tier configs and diff by hand.
- **Tradeoff:** Doubles/triples the cost per eval run. Only run this on manual dispatch or on a weekly schedule, not nightly.

### Priority 3 — Absolute quality thresholds (not just regression)

> *"The bar nothing ships below."*

- **What to build:** A `quality_gate.json` file in the eval results directory, mirroring the baseline diff structure, with per-metric minimums. Example: `{"faithfulness": 3.8, "hallucination_rate": 0.15}`. The pipeline reports "under threshold" separately from "regressed from baseline." A regression below the absolute threshold is a hard block; a regression above it is a warning.
- **Why it matters:** Manifesto principle 1 (judgment codified) — the baseline tells you if you got worse; the threshold tells you if you're *already* bad. Both are judgment calls you currently make by reading the report.
- **Cost:** None — pure logic addition on top of existing data.

### Priority 4 — Judge/user-feedback calibration

Validate that the judge's definition of quality matches what users actually find useful.

- **What to build:** A periodic correlation report: for queries that have user feedback ('up'/'down'), run the judge on the stored answer and compare judge scores vs. actual feedback. Track `judge_feedback_agreement_rate` as an eval metric.
- **Why it matters:** Manifesto principle 5 (self-profiling) — the framework in your head includes "users find this useful," but the harness only knows what the judge thinks. If the judge and users disagree, the judge prompt needs tuning.
- **Cost:** One judge call per feedback-bearing query, run weekly.

### Priority 5 — Targeted bottleneck re-eval

> *"Drown it in tokens."*

- **What to build:** When a nightly run flags specific questions as regressed, automatically re-run *just those questions* with more expensive settings (e.g., a larger model for judging, multiple judge passes and take the median, wider retrieval pool_size) and report whether the regression was real or noise.
- **Why it matters:** Manifesto principle 3 (tokenmaxxing) — throw tokens at the specific part of the lifecycle that's tripping you up. Currently a single-point regression on a borderline question triggers the same alert as a genuine quality collapse.
- **Cost:** Minimal — only runs when there's an actual regression, and only on the failing questions.

### Priority 6 — Category-specific tolerances

- **What to build:** Extend the regression diff to support per-category tolerance overrides. Safety-critical topics (superannuation, residency, div7a) get a tighter tolerance; interpretive topics (PSI, trading_stock) get a wider one.
- **Why it matters:** Manifesto principle 1 — the judgment of which topics are consequential is currently in your head; it should be in the harness.
- **Cost:** Configuration only.

## What the harness does NOT need

Based on the manifesto's warning about betting on mechanics the labs will ship:

- **Don't build a custom context-compaction layer for the judge.** The labs ship that. LiteLLM already handles prompt caching (`cacheable_system` is used). If the judge's context exceeds the model window, the fix is a bigger model or shorter context — not a hand-rolled summarizer that'll be obsolete in two releases.
- **Don't build a custom sub-agent evaluator.** The manifesto specifically warns against this: "hand-built context management, custom sub-agent setups, the clever workarounds people roll by hand: the labs watch what works and ship it built in." A second LLM calling a third LLM to verify the first — the labs will ship that as a feature.
- **Don't over-invest in the heuristic accuracy suite.** It's fast and free, which is its value. But it's a keyword matcher — it can never tell you if an answer is *correct*, only if it mentions expected terms. Keep it as a fast pre-filter, not as a quality gate.
