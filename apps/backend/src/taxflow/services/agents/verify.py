import json
import re

from taxflow import providers
from taxflow.config import settings
from taxflow.ports.llm import StructuredParseError
from taxflow.services.agents.models import VerificationResult
from taxflow.services.prompt_cache import cacheable_system

SYSTEM_PROMPT = """You are a senior Australian tax lawyer reviewing an AI-drafted advice memo.
Check each factual claim in the draft against the provided source documents.

Return a JSON object with this exact schema:
{
  "overall_status": "verified" | "needs_correction" | "unreliable",
  "issues": [
    {
      "claim": "exact text from draft",
      "issue": "description of problem",
      "severity": "critical" | "warning" | "note",
      "source_says": "what the source actually says",
      "suggested_correction": "how to fix it"
    }
  ],
  "unsupported_claims": ["list of claims with no citation"],
  "overall_confidence": 0.0
}

Severity guide:
- critical: factually wrong based on the sources (wrong rate, wrong section number, wrong test)
- warning: potentially misleading or incomplete
- note: minor stylistic or formatting suggestion

Return ONLY valid JSON. No preamble or explanation."""

# The "insufficient information" sentinel the research agent emits (SYSTEM_PROMPT
# rule 5). Its presence is one of the risk signals that gate verification (B2).
INSUFFICIENT_PHRASE = "do not contain sufficient information"


def should_verify(confidence: float, citations: list[dict], answer: str) -> bool:
    """Gate the verify pass (Task B2): run ONLY on risky answers.

    Risky means any of:
      - low estimated confidence (< VERIFY_CONFIDENCE_THRESHOLD),
      - few/zero parsed citations (< VERIFY_MIN_CITATIONS),
      - the "insufficient information" phrase in the answer.
    A confident, well-cited answer skips the (expensive) verify call entirely.
    """
    if confidence < settings.VERIFY_CONFIDENCE_THRESHOLD:
        return True
    if len(citations) < settings.VERIFY_MIN_CITATIONS:
        return True
    if INSUFFICIENT_PHRASE in (answer or "").lower():
        return True
    return False


def verify_model_for(confidence: float, citations: list[dict], answer: str) -> str:
    """Pick the verify model (Task B2).

    Default is VERIFY_MODEL (Haiku). Sonnet is reserved for the most severely
    flagged answers — zero citations or the explicit "insufficient information"
    admission — where a stronger reviewer is worth the cost.
    """
    severe = not citations or INSUFFICIENT_PHRASE in (answer or "").lower()
    return (
        providers.resolve_model("verify_strong")
        if severe
        else providers.resolve_model("verify")
    )


def _parse_verification(text: str) -> dict:
    """Tolerantly extract the verification JSON (Task C3).

    Models often wrap JSON in ```json fences or add stray prose despite the
    instructions. Rather than fragile fence-stripping only, we try, in order:
      1. direct json.loads,
      2. fence-stripped json.loads,
      3. the first balanced {...} object found anywhere in the text.
    Falls back to a parse_error result (kept from the original) if all fail.
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
        "overall_status": "parse_error",
        "issues": [],
        "unsupported_claims": [],
        "overall_confidence": 0.0,
    }


def needs_correction(verification: dict) -> bool:
    """True when the verification warrants a caveat / corrective pass (Task C3).

    Fires on overall_status needs_correction/unreliable OR any critical issue.
    parse_error is treated as non-actionable (we couldn't read the result).
    """
    if verification.get("overall_status") in ("needs_correction", "unreliable"):
        return True
    return any(
        (issue or {}).get("severity") == "critical"
        for issue in verification.get("issues", [])
    )


def build_caveat(verification: dict) -> str:
    """A short, visible caveat to flag a risky verified answer (Task C3)."""
    status = verification.get("overall_status", "unknown")
    critical = [
        i for i in verification.get("issues", []) if (i or {}).get("severity") == "critical"
    ]
    parts = [
        "\u26a0\ufe0f Verification flagged this answer "
        f"(status: {status}). Please review against the cited sources before relying on it."
    ]
    if critical:
        parts.append(
            "Critical issues: "
            + "; ".join(i.get("issue", "") for i in critical if i.get("issue"))
        )
    return " ".join(parts)


class VerifyAgent:
    async def run(
        self,
        draft: str,
        citations: list[dict],
        question: str,
        model: str | None = None,
    ) -> dict:
        user = (
            f"Draft memo to verify:\n{draft}\n\n"
            f"Source documents for verification:\n{_format_citations(citations)}"
        )
        system = _system_blocks()
        resolved_model = model or providers.resolve_model("verify")
        try:
            result = await providers.get_llm().generate_structured(
                messages=[{"role": "user", "content": user}],
                system=system,
                model=resolved_model,
                output_model=VerificationResult,
                max_tokens=2000,
                temperature=0,
            )
        except StructuredParseError:
            # Structured validation failed: retry a plain generation with the SAME
            # prompt and run the tolerant parser over its text, so fenced/prose-
            # wrapped JSON (including a real needs_correction verdict) is still
            # recovered. _parse_verification returns the empty parse_error dict
            # only when that plain generation also can't be parsed.
            response = await providers.get_llm().generate(
                messages=[{"role": "user", "content": user}],
                system=system,
                model=resolved_model,
                max_tokens=2000,
                temperature=0,
            )
            return _parse_verification(response.text or "")
        # Bridge back to a dict so downstream persistence (query.py) is unchanged.
        return result.model_dump()


def _format_citations(citations: list[dict]) -> str:
    return "\n---\n".join(
        f"Citation: {c.get('citation')}\nContent: {c.get('content') or c.get('excerpt', '')}" for c in citations
    )


def _system_blocks() -> list[dict] | str:
    """The verify system prompt as a cacheable content block (Task B1).

    The prompt is large and fully static, so it forms a stable cacheable prefix;
    marking it ephemeral lets repeat verify calls read it from cache at ~10% of
    the input price."""
    return cacheable_system(SYSTEM_PROMPT)
