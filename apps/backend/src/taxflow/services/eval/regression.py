"""Baseline diff + run-log store (Task B3).

``diff_against_baseline`` compares a current aggregate against a stored baseline
and flags metrics that regressed beyond a tolerance, per-topic (``by_category``)
and per-tier (``by_model_used``). ``write_run`` appends a run record to
``runs.jsonl`` and rewrites the ``latest.json`` summary; ``load_baseline`` reads
``baseline.json``. No LLM/DB — plain JSON files.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
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


def diff_metrics(
    current: dict,
    baseline: dict,
    tolerance: float,
    higher_better: Iterable[str],
    lower_better: Iterable[str],
    *,
    null_skip: bool = False,
) -> dict:
    """Per-metric deltas + regression flags for one roll-up group.

    Generalises the eval diff so callers (e.g. production drift) supply their
    own ``higher_better`` / ``lower_better`` metric directions. A metric absent
    from BOTH iterables is not diffed (contextual only).

    ``null_skip`` (default ``False``) selects how absent/``None`` values are
    handled:

      - ``False`` (eval default): a missing or ``None`` value coerces to ``0.0``
        (``float(value or 0.0)``), exactly reproducing the historical
        ``diff_against_baseline`` behaviour byte-for-byte.
      - ``True`` (production drift): when a metric is ``None`` on either side —
        e.g. a Tier-1 column not yet present, so the metric is genuinely
        unavailable — the metric is skipped (``delta`` set to ``None``) and can
        never flag a regression, instead of being treated as a real ``0.0``.

    When ``baseline`` is empty (no baseline for this group yet), we still report
    deltas for context but flag NO regressions and set ``baseline_missing=True``
    — otherwise a lower-is-better metric (e.g. hallucination_rate) would be
    spuriously flagged as a regression against an implicit zero baseline on the
    very first run.
    """
    baseline_missing = not baseline
    deltas: dict = {}
    regressions: list[str] = []

    def _resolve(raw):
        """Return (delta_computable, value). When null_skip and raw is None,
        the metric is skipped; otherwise None coerces to 0.0 (legacy)."""
        if null_skip and raw is None:
            return False, None
        return True, float(raw or 0.0)

    for metric in higher_better:
        cur_ok, cur = _resolve(current.get(metric))
        base_ok, base = _resolve(baseline.get(metric))
        if not (cur_ok and base_ok):
            deltas[metric] = None
            continue
        delta = cur - base
        deltas[metric] = delta
        if not baseline_missing and delta < -tolerance:
            regressions.append(metric)
    for metric in lower_better:
        cur_ok, cur = _resolve(current.get(metric))
        base_ok, base = _resolve(baseline.get(metric))
        if not (cur_ok and base_ok):
            deltas[metric] = None
            continue
        delta = cur - base
        deltas[metric] = delta
        if not baseline_missing and delta > tolerance:
            regressions.append(metric)
    return {
        "deltas": deltas,
        "regressions": regressions,
        "baseline_missing": baseline_missing,
    }


def _diff_group(
    current: dict,
    baseline: dict,
    tolerance: float,
    higher_better: Iterable[str] = _HIGHER_BETTER,
    lower_better: Iterable[str] = _LOWER_BETTER,
) -> dict:
    """Eval-default wrapper over :func:`diff_metrics`.

    Defaults ``higher_better`` / ``lower_better`` to the eval field tuples so
    ``diff_against_baseline`` output is byte-identical to before. Kept as a thin
    shim for the existing eval call-sites.
    """
    return diff_metrics(current, baseline, tolerance, higher_better, lower_better)


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
