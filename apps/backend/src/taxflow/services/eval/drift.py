"""Task 3a-1: pure production-drift metric roll-up + diff.

No DB, no LLM, no I/O — plain dict transforms so it's trivially unit-testable
and reusable from the scheduler job (Task 3a-2). Two responsibilities:

  1. :func:`build_snapshot_aggregate` — reshape the Tier-2 ``QueriesRepo.stats``
     output into the ``{"overall": {...}}`` roll-up shape the diff/regression
     helper consumes, selecting the production metric set (and null-skipping
     metrics that are unavailable because the Tier-1 035 columns aren't present
     yet, i.e. ``stats`` returned ``None`` for them).
  2. :func:`diff_snapshot` — a thin wrapper over
     :func:`taxflow.services.eval.regression.diff_metrics` with the production
     metric directions, returning ``deltas`` / ``regressions`` /
     ``baseline_missing`` / ``has_regressions``.

The metric KEYS here match exactly what ``QueriesRepo.stats`` returns
(``feedback_down_rate``, ``verification_failure_rate``, ``avg_confidence``,
``avg_cost_usd``, ``p95_latency_ms``, ``citation_validity_rate``,
``query_volume``) — we never re-derive them.
"""

from __future__ import annotations

from taxflow.services.eval import regression

# Production metrics where HIGHER is better — a drop beyond tolerance is drift.
PRODUCTION_HIGHER_BETTER = (
    "avg_confidence",
    "citation_validity_rate",
)
# Production metrics where LOWER is better — a rise beyond tolerance is drift.
PRODUCTION_LOWER_BETTER = (
    "feedback_down_rate",
    "verification_failure_rate",
    "avg_cost_usd",
    "p95_latency_ms",
)

# The full production metric set carried on a snapshot, in a stable order.
# ``query_count`` is CONTEXT only (neither direction) — volume, not quality.
# ``avg_cost_usd`` / ``citation_validity_rate`` are null-skip: they come from
# the Tier-1 035 columns and may be absent (``stats`` returns ``None``) until
# that migration lands, so a missing value must never flag a regression.
_CONTEXT = ("query_count",)
_SNAPSHOT_METRICS = _CONTEXT + PRODUCTION_HIGHER_BETTER + PRODUCTION_LOWER_BETTER


def build_snapshot_aggregate(aggregates: dict) -> dict:
    """Reshape a Tier-2 ``QueriesRepo.stats`` dict into a drift roll-up.

    ``aggregates`` is one ``stats`` output (the current or baseline window).
    Returns ``{"overall": {<metric>: <value>}}`` with the production metric set.
    ``query_count`` is read from ``query_count`` (falling back to the
    ``query_volume`` key ``stats`` actually emits). Metrics whose source value
    is ``None`` (Tier-1 035 column absent) are carried through as ``None`` so
    :func:`diff_snapshot` null-skips them rather than treating them as ``0.0``.
    """
    aggregates = aggregates or {}
    overall: dict = {}
    for metric in _SNAPSHOT_METRICS:
        if metric == "query_count":
            # stats() emits the volume under ``query_volume``; accept either.
            value = aggregates.get("query_count", aggregates.get("query_volume"))
        else:
            value = aggregates.get(metric)
        overall[metric] = value
    return {"overall": overall}


def diff_snapshot(current: dict, baseline: dict, tolerance: float) -> dict:
    """Diff a current snapshot roll-up against a baseline roll-up.

    Both inputs are :func:`build_snapshot_aggregate` outputs. Thin wrapper over
    :func:`regression.diff_metrics` with the production direction tuples and
    ``null_skip=True`` so unavailable (``None``) metrics never flag a
    regression. Returns ``deltas`` / ``regressions`` / ``baseline_missing`` and
    a top-level ``has_regressions`` bool.
    """
    result = regression.diff_metrics(
        current.get("overall", {}),
        baseline.get("overall", {}),
        tolerance,
        PRODUCTION_HIGHER_BETTER,
        PRODUCTION_LOWER_BETTER,
        null_skip=True,
    )
    result["has_regressions"] = bool(result["regressions"])
    return result
