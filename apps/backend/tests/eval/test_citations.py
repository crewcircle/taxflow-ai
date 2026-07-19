"""Offline tests for citation-validity checking (Task B1). No LLM/DB."""

from __future__ import annotations

import json
from pathlib import Path

from taxflow.services.eval.citations import check_citation_validity

FIXTURES = Path(__file__).parent / "fixtures"
RESULTS = json.loads((FIXTURES / "run_results.json").read_text())


def test_clean_result_is_valid():
    out = check_citation_validity(RESULTS["clean_result"])
    assert out["valid"] is True
    assert out["fabricated_markers"] == []
    assert out["unmatched_citations"] == []
    assert out["total_citations"] == 2


def test_flags_fabricated_marker_and_unmatched_citation():
    out = check_citation_validity(RESULTS["fabricated_and_unmatched_result"])
    # [5] is outside 1..len(rendered_sources)==2.
    assert out["fabricated_markers"] == [5]
    # "Made-up ruling XYZ" is not in the rendered source set.
    assert "Made-up ruling XYZ" in out["unmatched_citations"]
    assert out["valid"] is False


def test_parent_expansion_flags_marker_beyond_rendered_but_within_candidates():
    # rendered_sources has 2 entries; candidates has 3 (two children collapsed
    # into one parent). A [3] is within len(candidates) but outside
    # len(rendered_sources) -> fabricated (guards the rendered-vs-raw distinction).
    out = check_citation_validity(RESULTS["parent_expansion_result"])
    assert out["fabricated_markers"] == [3]
    assert out["valid"] is False


def test_legacy_trace_falls_back_to_candidates():
    # No rendered_sources -> validate against candidates (len 3). [4] is fabricated.
    out = check_citation_validity(RESULTS["legacy_result"])
    assert out["fabricated_markers"] == [4]
    # Both parsed citations are present in candidates -> no unmatched.
    assert out["unmatched_citations"] == []
    assert out["valid"] is False
