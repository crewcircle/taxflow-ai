"""Offline tests for baseline diff + run-log store (Task B3)."""

from __future__ import annotations

import json

from taxflow.services.eval.regression import (
    diff_against_baseline,
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


def test_missing_baseline_group_treated_as_zero():
    current = _agg(category="new_topic")
    baseline = _agg()  # no by_category
    diff = diff_against_baseline(current, baseline, tolerance=0.05)
    # New category's higher-is-better metrics are positive deltas -> no regression.
    assert diff["by_category"]["new_topic"]["regressions"] == []


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
