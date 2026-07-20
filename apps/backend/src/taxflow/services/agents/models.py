"""Pydantic result models for structured LLM outputs (Task A4).

These models back the ``LLMPort.generate_structured`` calls in the verify agent,
the ATO letter classifier and the retrieval re-ranker. Field names and the
``Literal`` value sets mirror exactly what the current prose-JSON prompts emit
and what the existing tolerant fallback parsers accept, so the dict-shaped data
that flows downstream (persistence in ``query.py``, handler lookup in
``ato_response.py``) is unchanged after the ``.model_dump()`` bridge.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from taxflow.services.ato_correspondence.classifier import LETTER_TYPES

# Concrete Literal of valid letter types (kept in lock-step with LETTER_TYPES so
# the classifier's structured output rejects anything off-list).
LetterType = Literal[
    "bas_discrepancy",
    "audit_initiation",
    "penalty_notice",
    "garnishee_notice",
    "position_paper",
    "objection_result",
    "ato_debt_notice",
    "payment_plan_request",
    "lodgement_reminder",
    "audit_completion",
    "abn_cancellation",
    "gst_registration",
    "employer_obligations",
    "lifestyle_assets",
    "taxable_payments",
]

# Guard against drift between the runtime constant and the Literal above.
assert set(LETTER_TYPES) == set(LetterType.__args__), (
    "LetterType Literal is out of sync with classifier.LETTER_TYPES"
)


class VerificationIssue(BaseModel):
    """One flagged claim from the verify pass (matches the SYSTEM_PROMPT schema)."""

    claim: str
    issue: str
    severity: Literal["critical", "warning", "note"]
    source_says: str
    suggested_correction: str


class VerificationResult(BaseModel):
    """Structured verify-pass result (matches the SYSTEM_PROMPT schema)."""

    overall_status: Literal["verified", "needs_correction", "unreliable"]
    issues: list[VerificationIssue] = []
    unsupported_claims: list[str] = []
    overall_confidence: float = 0.0


class LetterClassification(BaseModel):
    """Structured ATO-letter classification (matches the classifier prompt)."""

    letter_type: LetterType
    confidence: float
    ato_reference: str | None = None
    taxpayer_name: str | None = None
    deadline_days: int | None = None
    amount_disputed: float | None = None
    key_issue: str


class RerankScores(BaseModel):
    """A mapping of candidate index -> relevance score from the re-ranker."""

    scores: dict[int, float] = {}


# --- Phase 4: clarifying questions -------------------------------------------


class ClarifyOption(BaseModel):
    """One selectable answer to a clarifying question.

    ``label`` is shown to the user; ``value`` is the machine token folded into
    the effective_question on re-submit. Options are ALWAYS populated (Phase 4
    requirement A): a clarify decision must present selectable choices, never a
    free-text-only prompt.
    """

    label: str
    value: str


class ClarifyQuestion(BaseModel):
    """A single clarifying question with its selectable options.

    ``allow_free_text`` defaults True so the user can always type an answer the
    options don't cover; the UI still shows an explicit "Skip — just answer"
    affordance so the user is never forced to respond.
    """

    prompt: str
    options: list[ClarifyOption] = []
    allow_free_text: bool = True


class ClarifyDecision(BaseModel):
    """Structured ambiguity-classifier result (matches CLARIFY_SYSTEM_PROMPT).

    ``needs_clarification`` gates the terminal clarify outcome; ``confidence`` is
    compared against ``CLARIFY_CONFIDENCE_THRESHOLD`` so a low-confidence
    ambiguity verdict still answers directly (fail-open). ``questions`` carries
    the 1-2 questions, each with 3-4 always-populated options.
    """

    needs_clarification: bool
    confidence: float = 0.0
    questions: list[ClarifyQuestion] = []


# --- Phase 4: suggested follow-ups -------------------------------------------


class FollowUpSuggestions(BaseModel):
    """Structured follow-up questions (async strategy only).

    The default ``inline`` strategy folds follow-ups into the generate call and
    parses them with ``research.split_follow_ups``; this model backs the
    documented ``async`` Haiku strategy's ``generate_structured`` call.
    """

    questions: list[str] = []
