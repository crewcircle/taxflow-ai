"""Pilot: score the existing baseline_deepseek_graph.json results with
DeepEval's LLM-judged RAG metrics instead of the hand-rolled score_answer()
heuristic, to test whether an LLM judge resolves the literalism failures
(scorer bugs, stale fixture facts) found by hand this session without any
more regex patching.

Does NOT re-run the pipeline - scores the answers already saved from the
last production-path benchmark run, so this is a pure scoring-method
comparison, not a new pipeline run. `excerpt` on each parsed citation (a
trimmed ~200-char preview, not the full retrieved chunk) stands in for
retrieval_context - good enough for a first pilot, but a real adoption would
want the actual full chunk text threaded through.

Judge model: DeepSeek V4 Flash via OpenRouter (openrouter/deepseek/deepseek-v4-flash).
Not the absolute cheapest OpenRouter model exists (Xiaomi MiMo-V2-Flash is
$0.09/$0.29 per 1M in/out) - but DeepSeek is CHEAPER on output tokens ($0.18
vs $0.29), which dominates cost for short judge verdicts, and it's already
proven reliable in this exact pipeline (used for baseline/verify/rerank
throughout this session) rather than introducing an unverified new model.

Metrics scoped to what needs no ground-truth reference answer (questions.json
only has expected_topics/expected_citations, not an ideal reference answer):
  - Faithfulness: does the answer's claims hold up against retrieval_context?
    Directly comparable to VerifyAgent's own grounding-check job.
  - AnswerRelevancy: does the answer actually address the question asked?

Requires OPENROUTER_API_KEY (same as the other experiment scripts).

Run: uv run --with deepeval python \\
     scripts/experiments/graphrag_accuracy/run_deepeval_pilot.py
"""
from __future__ import annotations

import asyncio
import json
import os

from common import RESULTS_DIR, load_questions, load_results
from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric
from deepeval.models.base_model import DeepEvalBaseLLM
from deepeval.test_case import LLMTestCase

JUDGE_MODEL = "openrouter/deepseek/deepseek-v4-flash"


class OpenRouterJudge(DeepEvalBaseLLM):
    """Minimal DeepEvalBaseLLM wrapping litellm.acompletion so the judge
    model is OpenRouter-routed rather than DeepEval's OpenAI default."""

    def load_model(self):
        import litellm

        return litellm

    def get_model_name(self) -> str:
        return JUDGE_MODEL

    def generate(self, prompt: str, schema=None) -> str:
        return asyncio.run(self.a_generate(prompt, schema))

    async def a_generate(self, prompt: str, schema=None) -> str:
        # DeepEval's own prompts ask for a JSON verdict but don't enforce it
        # on the model side - response_format nudges DeepSeek (via OpenRouter's
        # OpenAI-compatible endpoint) to actually return valid JSON instead of
        # prose-wrapped or fenced JSON that DeepEval's strict parser rejects.
        resp = await self.model.acompletion(
            model=JUDGE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            api_key=os.environ["OPENROUTER_API_KEY"],
            api_base="https://openrouter.ai/api/v1",
            # Faithfulness's claim-extraction step returns one JSON array entry
            # per factual claim in the answer - a long, detailed answer (this
            # pipeline's answers run 1500-2500+ chars) can extract 15-20+
            # claims, truncating mid-string at a smaller budget.
            max_tokens=4000,
            temperature=0,
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content or ""


def _test_case(question: dict, result: dict) -> LLMTestCase:
    retrieval_context = [
        f"{c.get('citation', '')}: {c.get('excerpt', '')}" for c in result.get("citations", [])
    ] or ["(no citations parsed)"]
    return LLMTestCase(
        input=question["question"],
        actual_output=result.get("answer") or "(empty - infra error)",
        retrieval_context=retrieval_context,
    )


async def main() -> None:
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise RuntimeError(
            "OPENROUTER_API_KEY not set - run "
            "`doppler secrets set OPENROUTER_API_KEY --project taxflow --config dev` first."
        )

    questions = {q["id"]: q for q in load_questions()}
    results = {r["id"]: r for r in load_results("baseline_deepseek_graph")}

    judge = OpenRouterJudge()
    faithfulness = FaithfulnessMetric(model=judge, include_reason=True)
    relevancy = AnswerRelevancyMetric(model=judge, include_reason=True)

    scored = []
    for qid in sorted(results):
        r = results[qid]
        if r.get("error"):
            print(f"[{qid}] SKIP - infra error ({r['error']})")
            continue
        q = questions[qid]
        tc = _test_case(q, r)
        print(f"[{qid}] {q['question'][:70]}...")
        try:
            await faithfulness.a_measure(tc)
            await relevancy.a_measure(tc)
        except Exception as e:  # noqa: BLE001 - one bad judge call must not kill the run
            print(f"  -> JUDGE FAILED: {e!r}")
            continue
        print(
            f"  -> faithfulness={faithfulness.score:.2f} "
            f"relevancy={relevancy.score:.2f}"
        )
        scored.append(
            {
                "id": qid,
                "faithfulness": faithfulness.score,
                "faithfulness_reason": faithfulness.reason,
                "answer_relevancy": relevancy.score,
                "answer_relevancy_reason": relevancy.reason,
            }
        )

    out_path = os.path.join(RESULTS_DIR, "deepeval_pilot.json")
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(scored, f, indent=2)

    n = len(scored)
    if n:
        avg_faith = sum(s["faithfulness"] for s in scored) / n
        avg_rel = sum(s["answer_relevancy"] for s in scored) / n
        print(f"\n{n} questions judged. avg faithfulness={avg_faith:.2f} avg relevancy={avg_rel:.2f}")
    print(f"Saved -> {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
