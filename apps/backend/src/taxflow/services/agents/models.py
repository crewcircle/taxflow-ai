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
