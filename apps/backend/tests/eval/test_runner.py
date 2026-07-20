"""Offline tests for the eval CLI wrapper (``runner.main``).

These test the CLI's gate/promote DECISION logic only — ``run_eval_pipeline``
(the paid Anthropic/OpenAI/DB path) is monkeypatched with a stub, so nothing
here makes a real LLM/DB call. They run in the normal offline suite.
"""

from __future__ import annotations

import json
from pathlib import Path

from taxflow.services.eval import runner


def _fake_outcome(*, has_regressions: bool) -> dict:
    diff = {
        "has_regressions": has_regressions,
        "overall": {"regressions": ["faithfulness"] if has_regressions else []},
    }
    return {
        "aggregate": {"overall": {}, "by_category": {}, "by_model_used": {}},
        "per_question": [],
        "diff": diff,
        "record": {},
    }


def _patch_pipeline(monkeypatch, *, has_regressions: bool) -> None:
    async def _stub(questions, *, k, results_dir, capture_context=True):
        return _fake_outcome(has_regressions=has_regressions)

    monkeypatch.setattr(runner, "run_eval_pipeline", _stub)


def _write_results(tmp_path: Path) -> Path:
    questions = tmp_path / "questions.json"
    questions.write_text(json.dumps([{"id": "q1", "question": "?", "expected_citations": []}]))
    results = tmp_path / "results"
    results.mkdir()
    # write_run is stubbed out (pipeline is faked), so seed latest.json ourselves.
    (results / "latest.json").write_text(json.dumps({"aggregate": {}}))
    return questions


def test_promote_skipped_when_regressions(tmp_path, monkeypatch):
    """--promote-baseline with a regressed run must NOT write baseline.json and
    must exit non-zero, even without --gate."""
    _patch_pipeline(monkeypatch, has_regressions=True)
    questions = _write_results(tmp_path)
    results = tmp_path / "results"

    code = runner.main(
        [
            "--questions",
            str(questions),
            "--output-dir",
            str(results),
            "--promote-baseline",
        ]
    )

    assert code == 1
    assert not (results / "baseline.json").exists()


def test_promote_writes_baseline_when_clean(tmp_path, monkeypatch):
    """--promote-baseline on a clean run copies latest.json -> baseline.json."""
    _patch_pipeline(monkeypatch, has_regressions=False)
    questions = _write_results(tmp_path)
    results = tmp_path / "results"

    code = runner.main(
        [
            "--questions",
            str(questions),
            "--output-dir",
            str(results),
            "--promote-baseline",
        ]
    )

    assert code == 0
    assert (results / "baseline.json").exists()
    assert json.loads((results / "baseline.json").read_text()) == {"aggregate": {}}


def test_gate_returns_nonzero_on_regression(tmp_path, monkeypatch):
    """--gate exits non-zero on a regression (existing behavior preserved)."""
    _patch_pipeline(monkeypatch, has_regressions=True)
    questions = _write_results(tmp_path)
    results = tmp_path / "results"

    code = runner.main(
        ["--questions", str(questions), "--output-dir", str(results), "--gate"]
    )

    assert code == 1
    # No promotion requested, so baseline.json is untouched.
    assert not (results / "baseline.json").exists()
