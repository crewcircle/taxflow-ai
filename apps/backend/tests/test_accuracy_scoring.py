"""Offline unit tests for the accuracy suite's score_answer() heuristic.

score_answer is a pure function (no LLM/DB), but it previously only had
coverage via tests/accuracy/ - which is marked @pytest.mark.accuracy and
excluded from CI because it makes 30+ real LLM calls. These tests exercise
the scoring logic itself directly, offline.
"""
from __future__ import annotations

from tests.accuracy.test_research_accuracy import score_answer


def _question(topics, citations):
    return {"expected_topics": topics, "expected_citations": citations}


def test_exact_citation_match_still_scores_full_credit():
    result = {
        "answer": "GST is payable under GST Act s.9-80 on the taxable portion.",
        "citations": [{"citation": "GST Act s.9-80"}],
    }
    s = score_answer(_question(["gst"], ["GST Act s.9-80"]), result)
    assert s["cit_ratio"] == 1.0


def test_natural_phrasing_of_correct_section_now_scores_credit():
    """Regression guard: a model that correctly cites the right section but
    phrases it naturally ("section 9-80 of the GST Act" instead of the
    literal "GST Act s.9-80" expected string) must not be scored as a miss -
    this exact case was found during the RAG-quality experiment: retrieval
    found precisely the right section and the model cited it correctly, but
    the old literal-substring check still scored cit_ratio=0."""
    result = {
        "answer": "Under section 9-80 of the GST Act, a mixed supply is apportioned so GST is payable only on the taxable part.",
        "citations": [{"citation": "GST Act"}],
    }
    s = score_answer(_question(["gst"], ["GST Act s.9-80"]), result)
    assert s["cit_ratio"] == 1.0


def test_wrong_section_does_not_score_credit():
    """The loosened match must still require the actual section number to
    appear - a citation to a different section of the same Act is not a
    match."""
    result = {
        "answer": "Under section 9-70 of the GST Act, the amount of GST is 10%.",
        "citations": [{"citation": "GST Act"}],
    }
    s = score_answer(_question(["gst"], ["GST Act s.9-80"]), result)
    assert s["cit_ratio"] == 0.0


def test_short_section_token_not_loosely_matched():
    """A one-character section token (e.g. "s.1") is too generic to safely
    loose-match against arbitrary numbers in the answer, so it's excluded
    from the loosened check (the literal full-string check still applies)."""
    result = {"answer": "The total was $123,000 across 1 income year.", "citations": []}
    s = score_answer(_question([], ["ITAA 1997 s.1"]), result)
    assert s["cit_ratio"] == 0.0


def test_natural_phrasing_of_correct_division_now_scores_credit():
    """Same brittleness as the section-number case but for "Act Div N" style
    expected citations - found via q14 of the RAG-quality experiment:
    retrieval found precisely Division 820, the model wrote "Division 820 of
    ITAA 1997" naturally, but the literal "itaa 1997 div 820" string never
    matched."""
    result = {
        "answer": "The thin capitalisation rules in Division 820 of ITAA 1997 apply when total debt deductions exceed $2 million.",
        "citations": [{"citation": "ITAA 1997"}],
    }
    s = score_answer(_question(["thin cap"], ["ITAA 1997 Div 820"]), result)
    assert s["cit_ratio"] == 1.0


def test_wrong_division_does_not_score_credit():
    result = {
        "answer": "Division 855 of ITAA 1997 deals with CGT for foreign residents.",
        "citations": [{"citation": "ITAA 1997"}],
    }
    s = score_answer(_question([], ["ITAA 1997 Div 820"]), result)
    assert s["cit_ratio"] == 0.0


def test_section_field_credited_even_when_citation_label_is_bare():
    """Hierarchical chunking carries the retrieved section's own heading
    breadcrumb in the citation dict's `section` field (e.g. "... > Section
    25-35 (Bad debts)"), while `citation` often stays a bare Act name. Found
    via q09 of the production-path benchmark: real citations = ["ITAA 1997"]
    only, but its `section` field was an exact match for the expected
    "ITAA 1997 s.25-35" - the citation-only check could never see it."""
    result = {
        "answer": "A company can deduct a bad debt written off in the income year.",
        "citations": [
            {"citation": "ITAA 1997", "section": "Division 25 > Section 25-35 (Bad debts)"}
        ],
    }
    s = score_answer(_question(["bad debt"], ["ITAA 1997 s.25-35"]), result)
    assert s["cit_ratio"] == 1.0


def test_section_field_wrong_section_still_not_credited():
    result = {
        "answer": "See the relevant division for details.",
        "citations": [
            {"citation": "ITAA 1997", "section": "Division 165 > Section 165-120 (To deduct a bad debt)"}
        ],
    }
    s = score_answer(_question([], ["ITAA 1997 s.25-35"]), result)
    assert s["cit_ratio"] == 0.0


def test_citation_without_section_marker_unaffected():
    """Expected citations with no 's.N' section marker (e.g. a ruling
    number) are untouched by the loosening - only the original literal
    match applies."""
    result = {"answer": "See TD 2019/6 for the benchmark rate.", "citations": [{"citation": "TD 2019/6"}]}
    s = score_answer(_question([], ["TD 2019/6"]), result)
    assert s["cit_ratio"] == 1.0

    result2 = {"answer": "No relevant ruling found.", "citations": []}
    s2 = score_answer(_question([], ["TD 2019/6"]), result2)
    assert s2["cit_ratio"] == 0.0
