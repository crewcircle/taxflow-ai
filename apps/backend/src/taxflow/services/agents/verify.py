from taxflow import providers
from taxflow.config import settings
from taxflow.ports.llm import StructuredParseError
from taxflow.services.agents.models import VerificationResult
from taxflow.services.json_utils import extract_json_object
from taxflow.services.knowledge.pipeline import classify_topic
from taxflow.services.prompt_cache import cacheable_system

SYSTEM_PROMPT = """You are a senior Australian tax lawyer reviewing an AI-drafted advice memo.
Check each factual claim in the draft against the provided source documents.

Return a JSON object with this exact schema:
{
  "overall_status": "verified" | "needs_correction" | "unreliable",
  "issues": [
    {
      "claim": "exact text from draft",
      "issue": "ONE crisp sentence: what's wrong AND what the source actually says instead - a
                reader should understand the whole problem from this sentence alone, without
                needing a separate explanation",
      "severity": "critical" | "warning" | "note",
      "source_says": "OMIT this field entirely if it would just restate what you already said in
                      \"issue\" - only include it for a direct quote/figure from the source that
                      is too specific or important to paraphrase into \"issue\"",
      "suggested_correction": "ONE crisp sentence - the corrected claim itself, not a description
                               of how to correct it"
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


def _topic_mismatch(question: str, citations: list[dict]) -> bool:
    """True when the question confidently classifies to a specific topic but
    every actually-cited source classifies to a DIFFERENT specific topic.

    This is the exact failure mode a RAG-quality audit found undetected in
    production: a fluent, topically-correct-*sounding* answer citing sources
    from a completely unrelated area (e.g. NSW state payroll-tax rulings
    cited for a federal FBT question) - `_estimate_confidence` only counts
    citation/chunk quantity, so it scored these HIGH and `should_verify`
    never even ran. `classify_topic` is the same cheap regex classifier
    already used at ingestion time (no LLM call), reused here symmetrically
    on the query and on each cited source.

    Deliberately conservative: never trips on unclassified/generic content on
    either side (a `None` topic - most chunks - is not evidence of anything),
    only on a confident clash between two specific topics.
    """
    question_topic = classify_topic("", "", question)
    if question_topic is None or not citations:
        return False
    cited_topics = {
        classify_topic("", c.get("citation") or "", c.get("excerpt") or "") for c in citations
    }
    cited_topics.discard(None)
    if not cited_topics:
        return False
    return question_topic not in cited_topics


def should_verify(
    confidence: float, citations: list[dict], answer: str, question: str = ""
) -> bool:
    """Gate the verify pass (Task B2): run ONLY on risky answers.

    Risky means any of:
      - low estimated confidence (< VERIFY_CONFIDENCE_THRESHOLD),
      - few/zero parsed citations (< VERIFY_MIN_CITATIONS),
      - the "insufficient information" phrase in the answer,
      - the cited sources don't topically match the question (see
        ``_topic_mismatch``) - added after a RAG-quality audit found this
        exact case slipping through the citation-count-based confidence
        score undetected.
    A confident, well-cited, topically-grounded answer skips the (expensive)
    verify call entirely. ``question`` defaults to "" for callers that don't
    have it handy - the topic-mismatch check simply never trips in that case,
    same as before this signal existed.
    """
    if confidence < settings.VERIFY_CONFIDENCE_THRESHOLD:
        return True
    if len(citations) < settings.VERIFY_MIN_CITATIONS:
        return True
    if INSUFFICIENT_PHRASE in (answer or "").lower():
        return True
    if question and _topic_mismatch(question, citations):
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

    Delegates the fence/prose-tolerant JSON extraction to the shared
    :func:`extract_json_object` helper, then applies verify's own fallback: a
    parse_error verdict when no JSON object could be recovered.
    """
    result = extract_json_object(text)
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
