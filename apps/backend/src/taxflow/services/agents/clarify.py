"""Clarifying-questions agent (Phase 4).

Mirrors ``verify.py``: a cheap pure-Python pre-filter (``should_clarify``,
mirroring ``should_verify``) gates a Haiku ambiguity classifier
(``ClarifyAgent.run``) that uses the established structured-output pattern —
``LLMPort.generate_structured`` + Pydantic validation raising
``StructuredParseError``, with a tolerant plain-generation fallback. On any
unrecoverable parse failure the agent FAILS OPEN (no clarification, answer
directly), so a classifier hiccup never blocks an answer.

The classifier only runs when the free retrieval signals + question heuristics
flag a candidate, so clear questions pay nothing (see the cost analysis in the
sub-plan). Options are ALWAYS populated (requirement A).
"""

from __future__ import annotations

import re

from taxflow import providers
from taxflow.config import settings
from taxflow.ports.llm import StructuredParseError
from taxflow.services.agents.models import ClarifyDecision
from taxflow.services.json_utils import extract_json_object
from taxflow.services.prompt_cache import cacheable_system

CLARIFY_SYSTEM_PROMPT = """You are a triage assistant for an Australian tax research tool.
Decide whether a practitioner's question is too ambiguous to answer well WITHOUT
first asking a short clarifying question. Only ask when a genuinely different,
materially-wrong answer would result depending on an unstated detail (e.g. which
tax regime, which entity type, which concession, which year). A well-specified
question must NOT be clarified.

Return a JSON object with this exact schema:
{
  "needs_clarification": true | false,
  "confidence": 0.0,
  "questions": [
    {
      "prompt": "the clarifying question",
      "options": [
        {"label": "human-readable choice", "value": "short machine token"}
      ],
      "allow_free_text": true
    }
  ]
}

Rules:
- Ask AT MOST 2 questions, each with 3-4 concrete, mutually-distinct options.
- options must ALWAYS be populated — never present a question with no options.
- confidence is your confidence (0.0-1.0) that the question is genuinely ambiguous.
- When the question is clear, return needs_clarification=false with an empty questions list.
- Return ONLY valid JSON. No preamble or explanation."""

# Weak intent verbs that signal a well-formed question when present. A question
# with none of these AND that is very short is a candidate for clarification.
_INTENT_PATTERN = re.compile(
    r"\b(how|what|when|which|can|does|do|is|are|should|will|would|"
    r"explain|calculate|claim|apply|treat|deduct|report|lodge|assess)\b",
    re.IGNORECASE,
)
_WORD_PATTERN = re.compile(r"\b\w+\b")

# Short-question threshold: a question of this many words or fewer is a
# clarification candidate ("GST?", "Div 7A"). Kept as a local constant (not a
# config field) so the heuristic stays local to the gate; tune here if eval
# shows drift.
_CLARIFY_MIN_WORDS = 4


def should_clarify(
    question: str,
    signals: dict,
    prior_turns_used: int,
    has_clarifications: bool,
) -> bool:
    """Deterministic pre-filter (Phase 4), mirroring ``should_verify``.

    Returns True ONLY for genuinely under-specified candidate questions, so a
    well-formed question never reaches the (paid) classifier. No LLM call.

    Fails closed (never clarify) on the anti-annoyance guardrails:
      - the request already carries clarifications (this IS the round-trip answer),
      - a follow-up turn that already has session context (prior_turns_used > 0).

    Otherwise flags a candidate when the question is very short / lacks a clear
    intent verb, OR retrieval itself is weak (insufficient / no chunks / low top
    score) — the same free signals ``route_model`` already consumes.
    """
    if has_clarifications or prior_turns_used > 0:
        return False

    text = (question or "").strip()
    words = _WORD_PATTERN.findall(text)
    # Very short questions are the classic under-specified case ("GST?", "Div 7A").
    if len(words) <= _CLARIFY_MIN_WORDS:
        return True
    # No clear intent verb -> likely a bare topic/entity rather than a question.
    if not _INTENT_PATTERN.search(text):
        return True
    # Weak retrieval: the tool couldn't confidently find grounding, which often
    # tracks an ambiguous ask worth clarifying.
    if signals.get("insufficient") or signals.get("num_chunks", 0) == 0:
        return True
    return False


def clarify_model_for() -> str:
    """The clarify classifier model — resolved via the tier abstraction so no
    model id is hardcoded in services (architecture gate)."""
    return providers.resolve_model("clarify")


def enforce_option_caps(decision: ClarifyDecision) -> ClarifyDecision:
    """Trim AND validate a decision, then fail open if it is unusable.

    Anti-annoyance guardrail: even if the classifier over-produces, we present at
    most ``CLARIFY_MAX_QUESTIONS`` questions, each with at most
    ``CLARIFY_MAX_OPTIONS`` options.

    Validity guardrail (B1): a terminal clarify outcome is only useful if it can
    render selectable chips. So when ``needs_clarification`` is true we DROP any
    question that has no options, and if nothing usable remains (no questions, or
    every question was optionless) we FAIL OPEN to ``_no_clarify()`` — answering
    directly rather than short-circuiting the graph into a dead-end clarify card
    with no choices. Returns a new ClarifyDecision (does not mutate in place).
    """
    max_q = settings.CLARIFY_MAX_QUESTIONS
    max_o = settings.CLARIFY_MAX_OPTIONS
    trimmed_questions = []
    for question in decision.questions[:max_q]:
        options = question.options[:max_o]
        # Drop optionless questions when clarifying — they cannot render chips.
        if decision.needs_clarification and not options:
            continue
        trimmed_questions.append(question.model_copy(update={"options": options}))
    if decision.needs_clarification and not trimmed_questions:
        # Nothing usable to ask — answer directly instead of a dead-end card.
        return ClarifyDecision.model_validate(_no_clarify())
    return decision.model_copy(update={"questions": trimmed_questions})


def _no_clarify() -> dict:
    """The fail-open default: answer directly, no clarification."""
    return {"needs_clarification": False, "confidence": 0.0, "questions": []}


def _summarise_signals(signals: dict) -> str:
    """A SHORT retrieval summary for the classifier input — NOT the full context
    string (keeps the classify call cheap, per the cost analysis)."""
    return (
        f"Retrieval signals: num_chunks={signals.get('num_chunks', 0)}, "
        f"top_score={round(signals.get('top_score', 0.0) or 0.0, 4)}, "
        f"insufficient={bool(signals.get('insufficient'))}."
    )


class ClarifyAgent:
    async def run(
        self,
        question: str,
        signals: dict,
        model: str | None = None,
    ) -> dict:
        """Classify whether ``question`` is ambiguous, using the structured-output
        pattern with a tolerant fallback (mirrors ``VerifyAgent.run``).

        The input is deliberately small (the question + a short retrieval
        summary), so the classify call stays sub-cent. On StructuredParseError we
        retry a plain generation and tolerantly parse; if that is also
        unrecoverable we FAIL OPEN to no-clarify.
        """
        user = (
            f"Practitioner question:\n{question}\n\n{_summarise_signals(signals)}"
        )
        system = cacheable_system(CLARIFY_SYSTEM_PROMPT)
        resolved_model = model or clarify_model_for()
        try:
            result = await providers.get_llm().generate_structured(
                messages=[{"role": "user", "content": user}],
                system=system,
                model=resolved_model,
                output_model=ClarifyDecision,
                max_tokens=800,
                temperature=0,
            )
        except StructuredParseError:
            response = await providers.get_llm().generate(
                messages=[{"role": "user", "content": user}],
                system=system,
                model=resolved_model,
                max_tokens=800,
                temperature=0,
            )
            parsed = extract_json_object(response.text or "")
            if parsed is None:
                return _no_clarify()
            try:
                result = ClarifyDecision.model_validate(parsed)
            except Exception:  # noqa: BLE001 - fail open on any validation error
                return _no_clarify()
        return enforce_option_caps(result).model_dump()
