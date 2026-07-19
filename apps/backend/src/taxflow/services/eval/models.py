"""Pydantic result model for the LLM-as-judge (Task B2).

Mirrors the ``services/agents/models.py`` style (``Literal``/bounded ints) so the
``.model_dump()`` bridge in :class:`taxflow.services.eval.judge.EvalJudge` yields
the same dict shape the tolerant fallback parser produces.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class JudgeScore(BaseModel):
    """Structured judge verdict (matches the judge SYSTEM_PROMPT schema)."""

    faithfulness: int = Field(ge=1, le=5)
    relevance: int = Field(ge=1, le=5)
    citation_correctness: int = Field(ge=1, le=5)
    hallucination: bool = False
    unsupported_claims: list[str] = []
    rationale: str = ""
