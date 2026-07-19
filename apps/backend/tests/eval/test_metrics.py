"""Offline tests for retrieval metrics (Task B1). No LLM/DB/network."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from taxflow.services.eval.metrics import (
    match_citation,
    mrr,
    ndcg_at_k,
    recall_at_k,
)

FIXTURES = Path(__file__).parent / "fixtures"
CASES = json.loads((FIXTURES / "metrics_cases.json").read_text())


# --- match_citation ----------------------------------------------------------


def test_match_citation_case_insensitive_containment_both_directions():
    assert match_citation("ITAA 1997 s.8-1", {"itaa 1997"}) is True
    assert match_citation("ITAA 1997", {"ITAA 1997 s.8-1"}) is True
    assert match_citation("GSTR 2001/8", {"ITAA 1997"}) is False


def test_match_citation_empty_never_matches():
    assert match_citation("", {"ITAA 1997"}) is False
    assert match_citation("ITAA 1997", set()) is False


# --- recall / mrr against fixtures with hand-computed values ------------------


@pytest.mark.parametrize("name", list(CASES.keys()))
def test_recall_and_mrr_match_fixture(name):
    case = CASES[name]
    gold = set(case["gold"])
    assert recall_at_k(case["retrieved"], gold, case["k"]) == pytest.approx(
        case["expected_recall"]
    )
    assert mrr(case["retrieved"], gold) == pytest.approx(case["expected_mrr"])


def test_recall_zero_k_is_zero():
    assert recall_at_k(["ITAA 1997"], {"ITAA 1997"}, 0) == 0.0


# --- nDCG: binary + graded ---------------------------------------------------


def test_ndcg_perfect_ranking_is_one():
    assert ndcg_at_k(["ITAA 1997", "TR 2007/2"], {"ITAA 1997", "TR 2007/2"}, 2) == pytest.approx(1.0)


def test_ndcg_empty_gold_is_one():
    assert ndcg_at_k(["x"], set(), 3) == pytest.approx(1.0)


def test_ndcg_no_hit_is_zero():
    assert ndcg_at_k(["noise"], {"ITAA 1997"}, 3) == 0.0


def test_ndcg_binary_hit_at_rank_two():
    # one relevant item retrieved at rank 2 -> DCG = 1/log2(3); ideal = 1/log2(2)=1
    got = ndcg_at_k(["noise", "ITAA 1997"], {"ITAA 1997"}, 3)
    assert got == pytest.approx(1.0 / math.log2(3))


def test_ndcg_graded_uses_grades():
    # gold grades: A=2 (highly relevant), B=1. Retrieved order B, A.
    grades = {"A ruling": 2.0, "B ruling": 1.0}
    gold = set(grades)
    got = ndcg_at_k(["B ruling", "A ruling"], gold, 2, grades=grades)
    dcg = 1.0 / math.log2(2) + 2.0 / math.log2(3)
    idcg = 2.0 / math.log2(2) + 1.0 / math.log2(3)
    assert got == pytest.approx(dcg / idcg)
