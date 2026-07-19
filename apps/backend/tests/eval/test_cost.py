"""Offline tests for token->$ cost + quality-per-dollar (Task B3)."""

from __future__ import annotations

import pytest

from taxflow.config import settings
from taxflow.services.eval.cost import quality_per_dollar, run_cost


def test_run_cost_input_output(monkeypatch):
    monkeypatch.setattr(
        settings,
        "EVAL_MODEL_PRICING",
        {"haiku": {"input": 1.0, "output": 5.0}},
    )
    # 1M input @ $1 + 1M output @ $5 = $6
    assert run_cost("haiku", 1_000_000, 1_000_000) == pytest.approx(6.0)


def test_run_cost_with_cache_rates(monkeypatch):
    monkeypatch.setattr(
        settings,
        "EVAL_MODEL_PRICING",
        {"sonnet": {"input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_creation": 3.75}},
    )
    # 100k input, 10k output, 1M cache_read, 0 cache_creation
    cost = run_cost("sonnet", 100_000, 10_000, cache_read=1_000_000, cache_creation=0)
    expected = (100_000 * 3.0 + 10_000 * 15.0 + 1_000_000 * 0.3) / 1_000_000
    assert cost == pytest.approx(expected)


def test_run_cost_cache_falls_back_to_input_rate(monkeypatch):
    monkeypatch.setattr(
        settings, "EVAL_MODEL_PRICING", {"haiku": {"input": 2.0, "output": 4.0}}
    )
    # No cache_read rate defined -> uses input rate (2.0).
    cost = run_cost("haiku", 0, 0, cache_read=1_000_000)
    assert cost == pytest.approx(2.0)


def test_run_cost_unknown_tier_is_zero():
    assert run_cost("nope", 1_000_000, 1_000_000) == 0.0


def test_quality_per_dollar():
    assert quality_per_dollar(4.5, 0.9) == pytest.approx(5.0)


def test_quality_per_dollar_zero_cost_is_zero():
    assert quality_per_dollar(4.5, 0.0) == 0.0
    assert quality_per_dollar(4.5, -1.0) == 0.0
