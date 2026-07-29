"""
Accuracy test suite for the Research Agent.
Tests 30 AU tax questions against expected topics and citation presence.
Grade: PASS if >= 24/30 questions score >= 4/5 (80% pass rate).

This test is expensive (30+ LLM calls) and requires ANTHROPIC_API_KEY with credits.
It is excluded from CI. Run manually:
    uv run pytest tests/accuracy/ -v -s -m accuracy
"""
import json
import re
from pathlib import Path

import pytest

from taxflow.services.agents.research import ResearchAgent

QUESTIONS = json.loads((Path(__file__).parent / "questions.json").read_text())

pytestmark = pytest.mark.accuracy


@pytest.fixture
def agent():
    return ResearchAgent()


# Pulls the section/subsection token out of an "Act s.N" style expected
# citation (e.g. "GST Act s.9-80" -> "9-80", "ITAA 1936 s.170" -> "170").
_SECTION_TOKEN_RE = re.compile(r"\bs\.?\s*(\d[\d\-a-z]*)", re.IGNORECASE)
# Same idea for "Act Div N" style expected citations (e.g. "ITAA 1997 Div
# 820" -> "820"). A model correctly saying "Division 820 of ITAA 1997"
# doesn't match the literal "itaa 1997 div 820" string either.
_DIVISION_TOKEN_RE = re.compile(r"\bdiv\.?\s*(\d[\d\-a-z]*)", re.IGNORECASE)


def score_answer(question: dict, result: dict) -> dict:
    """Automated 1-5 scoring heuristic approximating human review.
    5: strong topic coverage and citations; 4: good; 3: partial; 2: vague; 1: wrong/no content.
    """
    answer = result.get("answer", "").lower()
    citations = [c.get("citation", "").lower() for c in result.get("citations", [])]
    # Hierarchical chunking (RAG-quality audit Fix 1) carries the retrieved
    # section's own heading breadcrumb in `section` (e.g. "... > Section 25-35
    # (Bad debts)") - the `citation` field alone often stays a bare Act name
    # ("ITAA 1997"). A citation dict can be exactly right at the section level
    # while `citation` says nothing more specific than the Act - found via q09
    # of the production-path benchmark: real citations = ["ITAA 1997"] only,
    # but its `section` field was "...Section 25-35 (Bad debts)", an EXACT
    # match for the expected "ITAA 1997 s.25-35" that the citation-only check
    # could never see.
    sections = [(c.get("section") or "").lower() for c in result.get("citations", [])]

    expected_topics = [t.lower() for t in question.get("expected_topics", [])]
    topics_covered = sum(1 for t in expected_topics if t in answer)
    topic_ratio = topics_covered / max(len(expected_topics), 1)

    expected_cits = [c.lower() for c in question.get("expected_citations", [])]

    def _cited(ec: str) -> bool:
        if any(ec in c for c in citations) or ec in answer:
            return True
        # A model correctly citing "section 9-80 of the GST Act" or "Division
        # 820 of ITAA 1997" won't match the literal "gst act s.9-80" /
        # "itaa 1997 div 820" strings above - accept a bare match on just the
        # section/division token too (e.g. "9-80", "820") so natural phrasing
        # isn't scored as a miss when the actual citation is right. Checked
        # against the answer text, the citation label, AND the section
        # breadcrumb (see `sections` above).
        for pattern in (_SECTION_TOKEN_RE, _DIVISION_TOKEN_RE):
            m = pattern.search(ec)
            if m:
                token = m.group(1)
                if len(token) >= 2 and (
                    token in answer
                    or any(token in c for c in citations)
                    or any(token in s for s in sections)
                ):
                    return True
        return False

    cits_found = sum(1 for ec in expected_cits if _cited(ec))
    cit_ratio = cits_found / max(len(expected_cits), 1)

    if topic_ratio >= 0.8 and cit_ratio >= 0.5:
        score = 5
    elif topic_ratio >= 0.6 and cit_ratio >= 0.3:
        score = 4
    elif topic_ratio >= 0.4:
        score = 3
    elif topic_ratio >= 0.2:
        score = 2
    else:
        score = 1

    return {
        "score": score,
        "topic_ratio": round(topic_ratio, 2),
        "cit_ratio": round(cit_ratio, 2),
        "topics_covered": topics_covered,
        "topics_expected": len(expected_topics),
        "citations_found": cits_found,
        "citations_expected": len(expected_cits),
    }


@pytest.mark.asyncio
async def test_research_accuracy_suite(agent):
    results = []
    passed = 0

    for q in QUESTIONS:
        print(f"\n[{q['id']}] {q['question'][:80]}...")

        result = await agent.run(question=q["question"], client_id="test-client-accuracy")

        scoring = score_answer(q, result)
        results.append(
            {
                "id": q["id"],
                "question": q["question"][:60],
                "confidence": result.get("confidence"),
                "model": result.get("model_used"),
                "wall_ms": result.get("wall_time_ms"),
                **scoring,
            }
        )

        if scoring["score"] >= 4:
            passed += 1
            print(f"  PASS score={scoring['score']}/5 topics={scoring['topic_ratio']} cits={scoring['cit_ratio']}")
        else:
            print(f"  FAIL score={scoring['score']}/5 topics={scoring['topic_ratio']} cits={scoring['cit_ratio']}")
            print(f"  Answer preview: {result.get('answer', '')[:200]}")

    pass_rate = passed / len(QUESTIONS)
    print("\n=== ACCURACY SUMMARY ===")
    print(f"Passed: {passed}/{len(QUESTIONS)} ({pass_rate:.1%})  |  Target: 24/30 (80%)")

    failures = [r for r in results if r["score"] < 4]
    for f in failures:
        print(f"  [{f['id']}] score={f['score']} - {f['question']}")

    (Path(__file__).parent / "last_run_results.json").write_text(json.dumps(results, indent=2))

    assert pass_rate >= 0.80, (
        f"Accuracy gate FAILED: {passed}/{len(QUESTIONS)} ({pass_rate:.1%}) < 80% target. "
        f"See tests/accuracy/last_run_results.json for details."
    )
