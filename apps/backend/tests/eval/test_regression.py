"""Offline tests for baseline diff + run-log store (Task B3)."""

from __future__ import annotations

import json

from taxflow.services.eval.regression import (
    _HIGHER_BETTER,
    _LOWER_BETTER,
    _diff_group,
    diff_against_baseline,
    diff_metrics,
    load_baseline,
    write_run,
)


def _agg(recall=1.0, faith=5.0, halluc=0.0, qpd=100.0, category=None):
    group = {
        "recall_at_k": recall,
        "mrr": 1.0,
        "ndcg": 1.0,
        "faithfulness": faith,
        "relevance": 5.0,
        "citation_correctness": 5.0,
        "citation_validity_rate": 1.0,
        "hallucination_rate": halluc,
        "quality_score": faith,
        "quality_per_dollar": qpd,
    }
    out = {"overall": group, "by_category": {}, "by_model_used": {}}
    if category:
        out["by_category"][category] = dict(group)
    return out


def test_no_regression_within_tolerance():
    current = _agg(recall=0.98)
    baseline = _agg(recall=1.0)
    diff = diff_against_baseline(current, baseline, tolerance=0.05)
    assert diff["has_regressions"] is False
    assert diff["overall"]["regressions"] == []
    assert diff["overall"]["deltas"]["recall_at_k"] < 0


def test_regression_flagged_beyond_tolerance():
    current = _agg(recall=0.80)
    baseline = _agg(recall=1.0)
    diff = diff_against_baseline(current, baseline, tolerance=0.05)
    assert diff["has_regressions"] is True
    assert "recall_at_k" in diff["overall"]["regressions"]


def test_hallucination_rate_rise_is_regression():
    current = _agg(halluc=0.30)
    baseline = _agg(halluc=0.05)
    diff = diff_against_baseline(current, baseline, tolerance=0.05)
    assert "hallucination_rate" in diff["overall"]["regressions"]


def test_per_category_regression_flagged():
    current = _agg(category="cgt")
    current["by_category"]["cgt"]["recall_at_k"] = 0.5
    baseline = _agg(category="cgt")
    diff = diff_against_baseline(current, baseline, tolerance=0.05)
    assert "recall_at_k" in diff["by_category"]["cgt"]["regressions"]
    assert diff["has_regressions"] is True


def test_missing_baseline_group_flags_no_regression():
    current = _agg(category="new_topic")
    baseline = _agg()  # no by_category
    diff = diff_against_baseline(current, baseline, tolerance=0.05)
    entry = diff["by_category"]["new_topic"]
    # New category has no baseline -> baseline_missing, never a regression.
    assert entry["baseline_missing"] is True
    assert entry["regressions"] == []


def test_empty_baseline_never_reports_regression():
    # First run against a seeded-empty baseline: even a lower-is-better metric
    # (hallucination_rate) present in current must NOT be flagged.
    current = _agg(halluc=0.5)
    diff = diff_against_baseline(current, {}, tolerance=0.05)
    assert diff["overall"]["baseline_missing"] is True
    assert diff["overall"]["regressions"] == []
    assert diff["has_regressions"] is False


def test_present_baseline_is_not_missing():
    diff = diff_against_baseline(_agg(), _agg(), tolerance=0.05)
    assert diff["overall"]["baseline_missing"] is False


def test_load_baseline_missing_and_empty(tmp_path):
    assert load_baseline(tmp_path) == {}
    (tmp_path / "baseline.json").write_text("")
    assert load_baseline(tmp_path) == {}


def test_write_run_appends_jsonl_and_writes_latest(tmp_path):
    rec1 = {"run": 1, "aggregate": _agg()}
    rec2 = {"run": 2, "aggregate": _agg(recall=0.9)}
    write_run(rec1, tmp_path)
    write_run(rec2, tmp_path)

    lines = (tmp_path / "runs.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["run"] == 1
    assert json.loads(lines[1])["run"] == 2

    latest = json.loads((tmp_path / "latest.json").read_text())
    assert latest["run"] == 2


def test_load_baseline_roundtrip(tmp_path):
    (tmp_path / "baseline.json").write_text(json.dumps(_agg()))
    loaded = load_baseline(tmp_path)
    assert loaded["overall"]["recall_at_k"] == 1.0


# --- generalized helper: eval defaults stay byte-identical --------------------


def test_diff_group_default_matches_explicit_eval_tuples():
    # _diff_group defaults to the eval field tuples, so passing them explicitly
    # via diff_metrics must produce an identical dict.
    current = _agg(recall=0.80, halluc=0.30)["overall"]
    baseline = _agg()["overall"]
    default = _diff_group(current, baseline, tolerance=0.05)
    explicit = diff_metrics(
        current, baseline, 0.05, _HIGHER_BETTER, _LOWER_BETTER
    )
    assert default == explicit


def test_diff_metrics_reproduces_diff_against_baseline_overall():
    # The overall group from diff_against_baseline equals a direct diff_metrics
    # call with the eval tuples (proves the generalisation didn't change eval).
    current = _agg(recall=0.80, halluc=0.30)
    baseline = _agg()
    full = diff_against_baseline(current, baseline, tolerance=0.05)
    direct = diff_metrics(
        current["overall"], baseline["overall"], 0.05, _HIGHER_BETTER, _LOWER_BETTER
    )
    assert full["overall"] == direct


def test_eval_default_coerces_missing_to_zero():
    # Legacy (null_skip=False) behaviour: a missing metric coerces to 0.0 and
    # still produces a numeric delta, NOT None.
    current = {"recall_at_k": 0.5}  # missing every other metric
    baseline = {"recall_at_k": 1.0}
    out = diff_metrics(current, baseline, 0.05, _HIGHER_BETTER, _LOWER_BETTER)
    # hallucination_rate absent on both -> coerced to 0.0 -> delta 0.0 (not None)
    assert out["deltas"]["hallucination_rate"] == 0.0
    assert out["deltas"]["mrr"] == 0.0
    assert out["deltas"]["recall_at_k"] == -0.5


def test_null_skip_returns_none_delta_for_missing_metric():
    # Production (null_skip=True): a None value is skipped, delta is None, and
    # it can never be flagged as a regression.
    current = {"avg_confidence": None, "feedback_down_rate": 0.5}
    baseline = {"avg_confidence": 0.8, "feedback_down_rate": 0.1}
    out = diff_metrics(
        current,
        baseline,
        0.05,
        ("avg_confidence",),
        ("feedback_down_rate",),
        null_skip=True,
    )
    assert out["deltas"]["avg_confidence"] is None
    assert "avg_confidence" not in out["regressions"]
    assert "feedback_down_rate" in out["regressions"]
