"""Tests for the shared tolerant JSON extractor (services/json_utils)."""

from __future__ import annotations

from taxflow.services.json_utils import extract_json_object


def test_extract_plain_json():
    assert extract_json_object('{"a": 1}') == {"a": 1}


def test_extract_fenced_json():
    assert extract_json_object('```json\n{"a": 2}\n```') == {"a": 2}


def test_extract_json_with_surrounding_prose():
    text = 'Here you go:\n{"a": 3}\nHope that helps.'
    assert extract_json_object(text) == {"a": 3}


def test_extract_returns_none_on_garbage():
    assert extract_json_object("not json at all") is None
    assert extract_json_object("") is None


def test_extract_non_dict_json_returns_none():
    # A bare list/number is valid JSON but not an object.
    assert extract_json_object("[1, 2, 3]") is None
    assert extract_json_object("42") is None
