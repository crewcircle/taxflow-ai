"""Pure aggregation of per-question eval records (Task B3).

Rolls a list of per-question record dicts up into overall + per-``category`` +
per-``model_used`` summaries. No LLM/DB — every value is a mean/rate over the
input records.

Each per-question record is expected to carry (all optional, defaulted):
``category``, ``model_used``, ``recall_at_k``, ``mrr``, ``ndcg``,
``faithfulness``, ``relevance``, ``citation_correctness``, ``hallucination``
(bool), ``citation_valid`` (bool), ``cost`` (production $), ``judge_cost`` ($),
``latency_ms``.
"""

from __future__ import annotations

# Numeric fields averaged as plain means.
_MEAN_FIELDS = (
    "recall_at_k",
    "mrr",
    "ndcg",
    "faithfulness",
    "relevance",
    "citation_correctness",
    "cost",
    "judge_cost",
    "latency_ms",
)
# Boolean fields averaged as rates (fraction True).
_RATE_FIELDS = (
    ("hallucination", "hallucination_rate"),
    ("citation_valid", "citation_validity_rate"),
)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _summarise(records: list[dict]) -> dict:
    """One roll-up over a group of per-question records."""
    out: dict = {"count": len(records)}
    for field in _MEAN_FIELDS:
        out[field] = _mean([float(r.get(field, 0.0) or 0.0) for r in records])
    for field, label in _RATE_FIELDS:
        out[label] = _mean([1.0 if r.get(field) else 0.0 for r in records])

    # Aggregate judge-quality score = mean of the three 1-5 axes (production
    # quality signal), then quality-per-dollar over PRODUCTION cost only.
    quality = _mean(
        [
            _mean(
                [
                    float(r.get("faithfulness", 0.0) or 0.0),
                    float(r.get("relevance", 0.0) or 0.0),
                    float(r.get("citation_correctness", 0.0) or 0.0),
                ]
            )
            for r in records
        ]
    )
    total_prod_cost = sum(float(r.get("cost", 0.0) or 0.0) for r in records)
    from taxflow.services.eval.cost import quality_per_dollar

    out["quality_score"] = quality
    out["total_cost"] = total_prod_cost
    out["quality_per_dollar"] = quality_per_dollar(quality, total_prod_cost)
    return out


def _group_by(records: list[dict], key: str) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for r in records:
        value = r.get(key)
        if value is None:
            continue
        groups.setdefault(str(value), []).append(r)
    return groups


def aggregate(per_question: list[dict]) -> dict:
    """Aggregate per-question records into overall + per-category + per-model.

    Returns ``{"overall": {...}, "by_category": {...}, "by_model_used": {...}}``
    where every leaf is a :func:`_summarise` roll-up. ``quality_per_dollar`` in
    each roll-up is over the production cost only; ``judge_cost`` is reported
    separately as eval overhead.
    """
    return {
        "overall": _summarise(per_question),
        "by_category": {
            cat: _summarise(recs)
            for cat, recs in sorted(_group_by(per_question, "category").items())
        },
        "by_model_used": {
            model: _summarise(recs)
            for model, recs in sorted(_group_by(per_question, "model_used").items())
        },
    }
