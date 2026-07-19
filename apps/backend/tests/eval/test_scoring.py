"""Offline tests for eval aggregation roll-ups (Task B3)."""

from __future__ import annotations

import pytest

from taxflow.services.eval.scoring import aggregate


def _rec(**kw):
    base = dict(
        category="cgt",
        model_used="haiku",
        recall_at_k=1.0,
        mrr=1.0,
        ndcg=1.0,
        faithfulness=5,
        relevance=5,
        citation_correctness=5,
        hallucination=False,
        citation_valid=True,
        cost=0.001,
        judge_cost=0.01,
        latency_ms=1000,
    )
    base.update(kw)
    return base


def test_overall_means_and_rates():
    records = [
        _rec(recall_at_k=1.0, hallucination=False, citation_valid=True),
        _rec(recall_at_k=0.0, hallucination=True, citation_valid=False),
    ]
    agg = aggregate(records)
    overall = agg["overall"]
    assert overall["count"] == 2
    assert overall["recall_at_k"] == pytest.approx(0.5)
    assert overall["hallucination_rate"] == pytest.approx(0.5)
    assert overall["citation_validity_rate"] == pytest.approx(0.5)


def test_per_category_and_per_model_rollups():
    records = [
        _rec(category="cgt", model_used="haiku", faithfulness=4),
        _rec(category="gst", model_used="sonnet", faithfulness=2),
    ]
    agg = aggregate(records)
    assert set(agg["by_category"]) == {"cgt", "gst"}
    assert set(agg["by_model_used"]) == {"haiku", "sonnet"}
    assert agg["by_category"]["cgt"]["count"] == 1
    assert agg["by_model_used"]["sonnet"]["faithfulness"] == pytest.approx(2.0)


def test_quality_per_dollar_uses_production_cost_only():
    # quality = mean of the three axes = 5.0; production cost = 0.002 total.
    records = [
        _rec(cost=0.001, judge_cost=1.0),
        _rec(cost=0.001, judge_cost=1.0),
    ]
    agg = aggregate(records)
    overall = agg["overall"]
    assert overall["quality_score"] == pytest.approx(5.0)
    assert overall["total_cost"] == pytest.approx(0.002)
    # judge_cost is reported (mean) but excluded from quality_per_dollar.
    assert overall["judge_cost"] == pytest.approx(1.0)
    assert overall["quality_per_dollar"] == pytest.approx(5.0 / 0.002)


def test_records_without_category_or_model_are_skipped_in_rollups():
    records = [_rec(category=None, model_used=None)]
    agg = aggregate(records)
    assert agg["by_category"] == {}
    assert agg["by_model_used"] == {}
    assert agg["overall"]["count"] == 1
