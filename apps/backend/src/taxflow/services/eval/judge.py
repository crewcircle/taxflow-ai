"""LLM-as-judge for eval scoring (Task B2).

Scores a generated answer on faithfulness, relevance and citation-correctness,
and flags hallucinations, against the retrieved context. Mirrors the production
agents: constructs its LLM through ``providers.get_llm()`` and resolves its model
through ``providers.resolve_model(settings.EVAL_JUDGE_TIER)`` — it NEVER imports a
vendor SDK and NEVER passes a bare tier string to LiteLLM.

On a structured-parse failure it retries a plain generation and runs a tolerant
parser (copied from ``verify._parse_verification``), returning a ``parse_error``
verdict so a single malformed judge response never crashes an eval run.
"""

from __future__ import annotations

from taxflow import providers
from taxflow.config import settings
from taxflow.ports.llm import StructuredParseError
from taxflow.services.eval.models import JudgeScore
from taxflow.services.json_utils import extract_json_object
from taxflow.services.prompt_cache import cacheable_system

SYSTEM_PROMPT = """You are a senior Australian tax lawyer acting as an impartial \
examiner. You are grading an AI assistant's answer to a tax question against the \
source documents it was given. Judge ONLY against those sources — do not use \
outside knowledge to fill gaps, and treat the sources as the ground truth.

Grade the answer on three axes, each an integer from 1 (worst) to 5 (best):
- faithfulness: is every claim grounded in the provided sources? A claim not \
supported by the sources lowers this score, regardless of whether it is true in \
general (groundedness).
- relevance: does the answer actually address the question, and is it complete \
for what was asked (relevance/completeness)?
- citation_correctness: are the [N] citation markers used, and do they point to \
sources that genuinely support the cited claim?

Also return:
- hallucination: true if the answer states a fact, figure, section number or \
rate that is NOT supported by any provided source.
- unsupported_claims: the specific claims (as short strings) that lack source \
support.
- rationale: one or two sentences explaining the scores.

Australian-tax context: rates, thresholds, section references and ATO/tribunal \
positions must match the sources exactly; a plausible-but-unsupported figure is \
a hallucination.

Return ONLY a JSON object with this exact schema, no preamble or explanation:
{
  "faithfulness": 1-5,
  "relevance": 1-5,
  "citation_correctness": 1-5,
  "hallucination": true | false,
  "unsupported_claims": ["..."],
  "rationale": "..."
}"""


def _parse_judge(text: str) -> dict:
    """Tolerantly extract the judge JSON.

    Delegates the fence/prose-tolerant JSON extraction to the shared
    :func:`extract_json_object` helper, then applies the judge's own fallback: a
    ``parse_error`` verdict when no JSON object could be recovered.
    """
    result = extract_json_object(text)
    if result is not None:
        return result

    return {
        "faithfulness": 0,
        "relevance": 0,
        "citation_correctness": 0,
        "hallucination": False,
        "unsupported_claims": [],
        "rationale": "parse_error",
        "verdict": "parse_error",
    }


class EvalJudge:
    """LLM-as-judge. ``llm`` defaults to the composition-root ``get_llm()``."""

    def __init__(self, llm=None):
        self._llm = llm or providers.get_llm()

    async def score(
        self,
        *,
        question: str,
        answer: str,
        retrieved_context: str,
        citations: list[dict],
    ) -> dict:
        """Grade one answer. Returns a plain dict (JudgeScore fields).

        Resolves the judge model through ``providers.resolve_model`` — the same
        model-routing invariant as every production call-site — never a bare tier.
        On ``StructuredParseError`` retries a plain generation and tolerantly
        parses it, returning a ``parse_error`` verdict.
        """
        user = (
            f"Question:\n{question}\n\n"
            f"Sources the assistant was given:\n{retrieved_context}\n\n"
            f"Citations the assistant produced:\n{_format_citations(citations)}\n\n"
            f"Assistant's answer to grade:\n{answer}"
        )
        system = cacheable_system(SYSTEM_PROMPT)
        model = providers.resolve_model(settings.EVAL_JUDGE_TIER)
        try:
            result = await self._llm.generate_structured(
                messages=[{"role": "user", "content": user}],
                system=system,
                model=model,
                output_model=JudgeScore,
                max_tokens=1500,
                temperature=0,
            )
        except StructuredParseError:
            response = await self._llm.generate(
                messages=[{"role": "user", "content": user}],
                system=system,
                model=model,
                max_tokens=1500,
                temperature=0,
            )
            verdict = _parse_judge(response.text or "")
            # Prefer the real usage from the plain generation; estimate if absent.
            usage = getattr(response, "usage", None)
            verdict["judge_usage"] = _usage_dict(
                usage, prompt=SYSTEM_PROMPT + "\n" + user, output=response.text or ""
            )
            return verdict
        # Bridge to a dict so downstream aggregation stays dict-shaped.
        verdict = result.model_dump()
        # The structured path returns no Usage object, so estimate judge tokens
        # from the prompt + the rendered verdict — enough for the separate
        # judge_cost line (eval overhead, excluded from production QPD).
        verdict["judge_usage"] = _usage_dict(
            None, prompt=SYSTEM_PROMPT + "\n" + user, output=result.model_dump_json()
        )
        return verdict


def _usage_dict(usage, *, prompt: str, output: str) -> dict:
    """Judge token usage: the real Usage when non-zero, else a tokenizer estimate.

    Only ``input_tokens``/``output_tokens`` are needed for the judge_cost line;
    cache counters are irrelevant to eval-overhead accounting.
    """
    if usage is not None:
        try:
            input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
            output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        except (TypeError, ValueError):
            input_tokens = output_tokens = 0
        if input_tokens or output_tokens:
            return {"input_tokens": input_tokens, "output_tokens": output_tokens}
    tokenizer = providers.get_tokenizer()
    return {
        "input_tokens": tokenizer.count(prompt),
        "output_tokens": tokenizer.count(output),
    }


def _format_citations(citations: list[dict]) -> str:
    if not citations:
        return "(none)"
    return "\n---\n".join(
        f"Citation: {c.get('citation')}\nExcerpt: {c.get('excerpt') or c.get('content', '')}"
        for c in citations
    )
