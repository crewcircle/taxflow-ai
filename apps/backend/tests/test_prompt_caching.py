"""Tests for Anthropic prompt caching breakpoints (Task B1)."""
from taxflow.config import settings
from taxflow.services.agents import research, verify


def test_research_system_blocks_carry_cache_control_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "PROMPT_CACHE_ENABLED", True)
    blocks = research._system_blocks()
    assert isinstance(blocks, list)
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert blocks[0]["text"] == research.SYSTEM_PROMPT


def test_research_system_blocks_plain_string_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "PROMPT_CACHE_ENABLED", False)
    assert research._system_blocks() == research.SYSTEM_PROMPT


def test_verify_system_blocks_carry_cache_control_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "PROMPT_CACHE_ENABLED", True)
    blocks = verify._system_blocks()
    assert isinstance(blocks, list)
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert blocks[0]["text"] == verify.SYSTEM_PROMPT


def test_verify_system_blocks_plain_string_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "PROMPT_CACHE_ENABLED", False)
    assert verify._system_blocks() == verify.SYSTEM_PROMPT
