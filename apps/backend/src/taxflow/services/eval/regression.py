"""Baseline diff + run-log store (Task B3).

``diff_against_baseline`` compares a current aggregate against a stored baseline
and flags metrics that regressed beyond a tolerance, per-topic (``by_category``)
and per-tier (``by_model_used``). ``write_run`` appends a run record to
``runs.jsonl`` and rewrites the ``latest.json`` summary; ``load_baseline`` reads
``baseline.json``. No LLM/DB — plain JSON files.
"""

from __future__ import annotations

import json
from pathlib import Path

# Metrics where HIGHER is better — a drop beyond tolerance is a regression.
_HIGHER_BETTER = (
    "recall_at_k",
    "mrr",
    "ndcg",
    "faithfulness",
    "relevance",
    "citation_correctness",
    "citation_validity_rate",
    "quality_score",
    "quality_per_dollar",
)
# Metrics where LOWER is better — a rise beyond tolerance is a regression.
_LOWER_BETTER = ("hallucination_rate",)


def _diff_group(current: dict, baseline: dict, tolerance: float) -> dict:
    """Per-metric deltas + regression flags for one roll-up group.

    When ``baseline`` is empty (no baseline for this group yet), we still report
    deltas-vs-zero for context but flag NO regressions and set
    ``baseline_missing=True`` — otherwise a lower-is-better metric (e.g.
    hallucination_rate) would be spuriously flagged as a regression against an
    implicit zero baseline on the very first run.
    """
    baseline_missing = not baseline
    deltas: dict = {}
    regressions: list[str] = []
    for metric in _HIGHER_BETTER:
        cur = float(current.get(metric, 0.0) or 0.0)
        base = float(baseline.get(metric, 0.0) or 0.0)
        delta = cur - base
        deltas[metric] = delta
        if not baseline_missing and delta < -tolerance:
            regressions.append(metric)
    for metric in _LOWER_BETTER:
        cur = float(current.get(metric, 0.0) or 0.0)
        base = float(baseline.get(metric, 0.0) or 0.0)
        delta = cur - base
        deltas[metric] = delta
        if not baseline_missing and delta > tolerance:
            regressions.append(metric)
    return {
        "deltas": deltas,
        "regressions": regressions,
        "baseline_missing": baseline_missing,
    }


def diff_against_baseline(current: dict, baseline: dict, tolerance: float) -> dict:
    """Diff a current aggregate against a baseline aggregate.

    Both inputs are :func:`taxflow.services.eval.scoring.aggregate` outputs.
    Returns overall + per-topic + per-tier deltas with ``regressions`` flags, and
    a top-level ``has_regressions`` bool. A missing baseline group reports
    ``baseline_missing=True`` and flags NO regressions (so the first run, or a
    brand-new category/tier, never spuriously reports a regression).
    """
    result: dict = {
        "overall": _diff_group(
            current.get("overall", {}), baseline.get("overall", {}), tolerance
        ),
        "by_category": {},
        "by_model_used": {},
    }
    for group_key in ("by_category", "by_model_used"):
        cur_groups = current.get(group_key, {}) or {}
        base_groups = baseline.get(group_key, {}) or {}
        for name, cur in cur_groups.items():
            result[group_key][name] = _diff_group(
                cur, base_groups.get(name, {}), tolerance
            )

    has_regressions = bool(result["overall"]["regressions"])
    for group_key in ("by_category", "by_model_used"):
        for entry in result[group_key].values():
            if entry["regressions"]:
                has_regressions = True
    result["has_regressions"] = has_regressions
    return result


def load_baseline(results_dir: str | Path) -> dict:
    """Load ``baseline.json`` from ``results_dir``; ``{}`` when absent/empty."""
    path = Path(results_dir) / "baseline.json"
    if not path.exists():
        return {}
    text = path.read_text().strip()
    if not text:
        return {}
    return json.loads(text)


def write_run(record: dict, results_dir: str | Path) -> Path:
    """Append ``record`` to ``runs.jsonl`` and rewrite ``latest.json``.

    Returns the path to ``runs.jsonl``. Creates ``results_dir`` if needed.
    """
    directory = Path(results_dir)
    directory.mkdir(parents=True, exist_ok=True)
    runs_path = directory / "runs.jsonl"
    with runs_path.open("a") as fh:
        fh.write(json.dumps(record) + "\n")
    (directory / "latest.json").write_text(json.dumps(record, indent=2))
    return runs_path
