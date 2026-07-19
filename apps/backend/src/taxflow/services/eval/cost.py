"""Token → dollar cost + quality-per-dollar (Task B3).

Pure arithmetic over ``settings.EVAL_MODEL_PRICING`` (per-tier $/1M tokens). No
LLM/DB.

Cost accounting
---------------
:func:`quality_per_dollar` measures the *production pipeline* only — the
``ResearchAgent.run()`` tokens that a real user query would incur. The judge's
own tokens are eval overhead and are tracked separately (a ``judge_cost`` field),
NOT folded into the production quality-per-dollar figure. This keeps the A/B
model-swap comparison honest: we compare what production would cost, not the cost
of grading it.
"""

from __future__ import annotations

from taxflow.config import settings


def run_cost(
    model_tier: str,
    input_tokens: int,
    output_tokens: int,
    cache_read: int = 0,
    cache_creation: int = 0,
) -> float:
    """Dollar cost of one generation given a tier's per-1M-token pricing.

    ``cache_read``/``cache_creation`` are counted at their own rates when the
    tier defines them (Anthropic prompt-cache), otherwise they fall back to the
    plain ``input`` rate. Regular ``input_tokens`` should exclude the cached
    counters (matching the LLM Usage record's normalised counters). Unknown tier
    → 0.0.
    """
    pricing = settings.EVAL_MODEL_PRICING.get(model_tier)
    if not pricing:
        return 0.0
    per_million = 1_000_000
    input_rate = pricing.get("input", 0.0)
    output_rate = pricing.get("output", 0.0)
    cache_read_rate = pricing.get("cache_read", input_rate)
    cache_creation_rate = pricing.get("cache_creation", input_rate)
    cost = (
        input_tokens * input_rate
        + output_tokens * output_rate
        + cache_read * cache_read_rate
        + cache_creation * cache_creation_rate
    )
    return cost / per_million


def quality_per_dollar(agg_score: float, total_cost: float) -> float:
    """Aggregate quality per production dollar.

    ``total_cost`` MUST be the production-pipeline cost only (exclude judge
    overhead). Zero/negative cost → 0.0 (avoid a divide-by-zero blow-up).
    """
    if total_cost <= 0:
        return 0.0
    return agg_score / total_cost
