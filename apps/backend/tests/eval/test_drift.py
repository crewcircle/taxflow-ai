"""Task 3a-1: offline tests for pure production-drift roll-up + diff.

No DB/LLM: exercises ``build_snapshot_aggregate`` (roll-up + null-skip of
Tier-1-absent metrics) and ``diff_snapshot`` (flags a HIGHER-better drop and a
LOWER-better rise; a missing baseline never flags a regression).
"""

from __future__ import annotations

from taxflow.services.eval import drift


def _stats(
    query_volume=100,
    feedback_down_rate=0.10,
    verification_failure_rate=0.05,
    avg_confidence=0.80,
    avg_cost_usd=0.02,
    p95_latency_ms=1200.0,
    citation_validity_rate=0.90,
):
    """A Tier-2 QueriesRepo.stats-shaped dict (only the keys drift reads)."""
    return {
        "query_volume": query_volume,
        "feedback_down_rate": feedback_down_rate,
        "verification_failure_rate": verification_failure_rate,
        "avg_confidence": avg_confidence,
        "avg_cost_usd": avg_cost_usd,
        "p95_latency_ms": p95_latency_ms,
        "citation_validity_rate": citation_validity_rate,
    }


# --- build_snapshot_aggregate ------------------------------------------------


def test_build_snapshot_aggregate_rolls_up_all_metrics():
    agg = drift.build_snapshot_aggregate(_stats())
    overall = agg["overall"]
    # query_count is read from the stats query_volume key.
    assert overall["query_count"] == 100
    assert overall["feedback_down_rate"] == 0.10
    assert overall["verification_failure_rate"] == 0.05
    assert overall["avg_confidence"] == 0.80
    assert overall["avg_cost_usd"] == 0.02
    assert overall["p95_latency_ms"] == 1200.0
    assert overall["citation_validity_rate"] == 0.90


def test_build_snapshot_aggregate_prefers_explicit_query_count():
    stats = _stats()
    stats["query_count"] = 42
    agg = drift.build_snapshot_aggregate(stats)
    assert agg["overall"]["query_count"] == 42


def test_build_snapshot_aggregate_null_skips_tier1_absent_metrics():
    # 035 columns not present yet -> stats returns None for cost + validity.
    stats = _stats(avg_cost_usd=None, citation_validity_rate=None)
    overall = drift.build_snapshot_aggregate(stats)["overall"]
    assert overall["avg_cost_usd"] is None
    assert overall["citation_validity_rate"] is None
    # the always-present metrics still carry through.
    assert overall["avg_confidence"] == 0.80


def test_build_snapshot_aggregate_handles_empty_input():
    overall = drift.build_snapshot_aggregate({})["overall"]
    assert overall["query_count"] is None
    assert overall["avg_confidence"] is None


# --- diff_snapshot -----------------------------------------------------------


def test_no_regression_within_tolerance():
    cur = drift.build_snapshot_aggregate(_stats(avg_confidence=0.79))
    base = drift.build_snapshot_aggregate(_stats(avg_confidence=0.80))
    diff = drift.diff_snapshot(cur, base, tolerance=0.05)
    assert diff["has_regressions"] is False
    assert diff["regressions"] == []


def test_higher_better_drop_is_regression():
    # avg_confidence drops well beyond tolerance -> HIGHER-better regression.
    cur = drift.build_snapshot_aggregate(_stats(avg_confidence=0.60))
    base = drift.build_snapshot_aggregate(_stats(avg_confidence=0.80))
    diff = drift.diff_snapshot(cur, base, tolerance=0.05)
    assert diff["has_regressions"] is True
    assert "avg_confidence" in diff["regressions"]
    assert diff["deltas"]["avg_confidence"] < 0


def test_lower_better_rise_is_regression():
    # feedback_down_rate rises beyond tolerance -> LOWER-better regression.
    cur = drift.build_snapshot_aggregate(_stats(feedback_down_rate=0.30))
    base = drift.build_snapshot_aggregate(_stats(feedback_down_rate=0.10))
    diff = drift.diff_snapshot(cur, base, tolerance=0.05)
    assert diff["has_regressions"] is True
    assert "feedback_down_rate" in diff["regressions"]
    assert diff["deltas"]["feedback_down_rate"] > 0


def test_latency_rise_flags_with_ms_tolerance():
    # p95_latency_ms is LOWER-better; a big ms rise flags when tolerance is ms.
    cur = drift.build_snapshot_aggregate(_stats(p95_latency_ms=3000.0))
    base = drift.build_snapshot_aggregate(_stats(p95_latency_ms=1200.0))
    diff = drift.diff_snapshot(cur, base, tolerance=500.0)
    assert "p95_latency_ms" in diff["regressions"]


def test_query_count_is_context_not_a_regression():
    # A big query_count change never flags: it's contextual, not a quality dir.
    cur = drift.build_snapshot_aggregate(_stats(query_volume=5))
    base = drift.build_snapshot_aggregate(_stats(query_volume=5000))
    diff = drift.diff_snapshot(cur, base, tolerance=0.05)
    assert "query_count" not in diff["regressions"]


def test_missing_baseline_flags_no_regression():
    # First run: empty baseline -> baseline_missing, never a regression even
    # though a lower-is-better metric is present in current.
    cur = drift.build_snapshot_aggregate(_stats(feedback_down_rate=0.9))
    diff = drift.diff_snapshot(cur, {"overall": {}}, tolerance=0.05)
    assert diff["baseline_missing"] is True
    assert diff["regressions"] == []
    assert diff["has_regressions"] is False


def test_null_metric_never_flags_regression():
    # cost absent (Tier-1 035 not landed): even a wild change can't regress.
    cur = drift.build_snapshot_aggregate(_stats(avg_cost_usd=None))
    base = drift.build_snapshot_aggregate(_stats(avg_cost_usd=0.02))
    diff = drift.diff_snapshot(cur, base, tolerance=0.001)
    assert "avg_cost_usd" not in diff["regressions"]
    assert diff["deltas"]["avg_cost_usd"] is None


def test_production_direction_tuples_are_disjoint_and_expected():
    assert set(drift.PRODUCTION_HIGHER_BETTER).isdisjoint(drift.PRODUCTION_LOWER_BETTER)
    assert "avg_confidence" in drift.PRODUCTION_HIGHER_BETTER
    assert "citation_validity_rate" in drift.PRODUCTION_HIGHER_BETTER
    assert "feedback_down_rate" in drift.PRODUCTION_LOWER_BETTER
    assert "p95_latency_ms" in drift.PRODUCTION_LOWER_BETTER
    assert "avg_cost_usd" in drift.PRODUCTION_LOWER_BETTER
