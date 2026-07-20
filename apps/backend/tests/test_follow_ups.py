"""Tests for the inline follow-up suggestion helpers (Phase 4).

``split_follow_ups`` is tolerant like ``_parse_citations``: a missing or garbled
sentinel block leaves the answer unchanged and yields no follow-ups.
"""
from taxflow.config import settings
from taxflow.services.agents.research import (
    FOLLOW_UP_SENTINEL,
    follow_up_instruction,
    split_follow_ups,
)


def test_split_follow_ups_no_sentinel_returns_answer_unchanged():
    text = "A plain answer with no follow-up block [1]."
    clean, questions = split_follow_ups(text)
    assert clean == text
    assert questions == []


def test_split_follow_ups_extracts_questions_and_cleans_answer():
    text = (
        "The answer body [1].\n"
        + FOLLOW_UP_SENTINEL
        + "\nWhat about GST?\nHow is the CGT discount applied?"
    )
    clean, questions = split_follow_ups(text)
    assert clean == "The answer body [1]."
    assert questions == ["What about GST?", "How is the CGT discount applied?"]


def test_split_follow_ups_trims_list_markers():
    text = (
        "Answer.\n"
        + FOLLOW_UP_SENTINEL
        + "\n1. First question?\n- Second question?\n* Third question?"
    )
    clean, questions = split_follow_ups(text)
    assert questions == ["First question?", "Second question?", "Third question?"]


def test_split_follow_ups_caps_at_follow_up_count(monkeypatch):
    monkeypatch.setattr(settings, "FOLLOW_UP_COUNT", 2)
    text = FOLLOW_UP_SENTINEL + "\nQ1?\nQ2?\nQ3?\nQ4?"
    _, questions = split_follow_ups(text)
    assert questions == ["Q1?", "Q2?"]


def test_split_follow_ups_empty_string():
    clean, questions = split_follow_ups("")
    assert clean == ""
    assert questions == []


def test_follow_up_instruction_empty_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "FOLLOW_UP_ENABLED", False)
    assert follow_up_instruction() == ""


def test_follow_up_instruction_empty_when_non_inline_strategy(monkeypatch):
    monkeypatch.setattr(settings, "FOLLOW_UP_ENABLED", True)
    monkeypatch.setattr(settings, "FOLLOW_UP_STRATEGY", "async")
    assert follow_up_instruction() == ""


def test_follow_up_instruction_present_when_inline_enabled(monkeypatch):
    monkeypatch.setattr(settings, "FOLLOW_UP_ENABLED", True)
    monkeypatch.setattr(settings, "FOLLOW_UP_STRATEGY", "inline")
    instruction = follow_up_instruction()
    assert FOLLOW_UP_SENTINEL in instruction
