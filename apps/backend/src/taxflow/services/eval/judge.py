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

import json
import re

from taxflow import providers
from taxflow.config import settings
from taxflow.ports.llm import StructuredParseError
from taxflow.services.eval.models import JudgeScore
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
    """Tolerantly extract the judge JSON (copied from verify._parse_verification).

    Tries direct json.loads, then fence-stripped, then the first balanced
    ``{...}`` object; falls back to a ``parse_error`` verdict when all fail.
    """
    text = (text or "").strip()

    def _try(candidate: str) -> dict | None:
        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None

    result = _try(text)
    if result is not None:
        return result

    stripped = text
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else stripped
        stripped = stripped.rsplit("```", 1)[0].strip()
        result = _try(stripped)
        if result is not None:
            return result

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        result = _try(match.group(0))
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
            return _parse_judge(response.text or "")
        # Bridge to a dict so downstream aggregation stays dict-shaped.
        return result.model_dump()


def _format_citations(citations: list[dict]) -> str:
    if not citations:
        return "(none)"
    return "\n---\n".join(
        f"Citation: {c.get('citation')}\nExcerpt: {c.get('excerpt') or c.get('content', '')}"
        for c in citations
    )
