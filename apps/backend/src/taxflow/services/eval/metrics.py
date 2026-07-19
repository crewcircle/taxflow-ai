"""Retrieval-quality metrics (Task B1).

Pure functions over a ranked list of *retrieved* citation strings and a *gold*
set of relevant citations. No LLM, DB or network — everything here is
deterministic and unit-testable against hand-computed values.

The single matching rule (:func:`match_citation`) is deliberately isolated so it
can be swapped for a stricter matcher (e.g. section-level exact match) without
touching the metric functions.
"""

from __future__ import annotations

import math


def _normalise(citation: str) -> str:
    """Lower-case, collapse whitespace — the normalisation both sides share."""
    return " ".join((citation or "").lower().split())


def match_citation(retrieved_citation: str, gold_citations: set[str]) -> bool:
    """Does ``retrieved_citation`` match any gold citation?

    Single documented, swappable rule: normalised, case-insensitive containment
    in *either* direction — a retrieved "ITAA 1997 s.8-1" matches a gold
    "ITAA 1997" and vice-versa. Empty inputs never match.
    """
    r = _normalise(retrieved_citation)
    if not r:
        return False
    for gold in gold_citations:
        g = _normalise(gold)
        if not g:
            continue
        if g in r or r in g:
            return True
    return False


def recall_at_k(retrieved: list[str], gold: set[str], k: int) -> float:
    """Fraction of gold citations matched within the top-``k`` retrieved.

    Empty gold → 1.0 (nothing to find, trivially satisfied). k <= 0 → 0.0.
    """
    if not gold:
        return 1.0
    if k <= 0:
        return 0.0
    top = retrieved[:k]
    hit = sum(
        1 for g in gold if any(match_citation(r, {g}) for r in top)
    )
    return hit / len(gold)


def mrr(retrieved: list[str], gold: set[str]) -> float:
    """Reciprocal rank of the FIRST retrieved item that matches any gold.

    1/rank of the first hit (1-indexed); 0.0 when nothing matches. Empty gold →
    0.0 (MRR is undefined with no relevant item; we report 0 by convention).
    """
    if not gold:
        return 0.0
    for i, r in enumerate(retrieved, start=1):
        if match_citation(r, gold):
            return 1.0 / i
    return 0.0


def ndcg_at_k(
    retrieved: list[str],
    gold: set[str],
    k: int,
    grades: dict[str, float] | None = None,
) -> float:
    """Normalised DCG@k. Binary relevance by default; graded when ``grades``.

    ``grades`` maps a gold citation → its relevance grade (e.g. 2.0 highly
    relevant, 1.0 relevant). A retrieved item's gain is the grade of the gold it
    matches (1.0 in binary mode). The ideal DCG uses the best achievable ordering
    of the available gold grades. Empty gold → 1.0; k <= 0 → 0.0.
    """
    if not gold:
        return 1.0
    if k <= 0:
        return 0.0

    def _grade_for(retrieved_citation: str) -> float:
        best = 0.0
        for g in gold:
            if match_citation(retrieved_citation, {g}):
                gain = grades.get(g, 1.0) if grades else 1.0
                best = max(best, gain)
        return best

    dcg = 0.0
    for i, r in enumerate(retrieved[:k], start=1):
        gain = _grade_for(r)
        if gain:
            dcg += gain / math.log2(i + 1)

    # Ideal ordering: the highest gold grades first, capped at k.
    ideal_grades = sorted(
        (grades.get(g, 1.0) if grades else 1.0 for g in gold), reverse=True
    )[:k]
    idcg = sum(
        gain / math.log2(i + 1) for i, gain in enumerate(ideal_grades, start=1)
    )
    if idcg == 0.0:
        return 0.0
    return dcg / idcg
