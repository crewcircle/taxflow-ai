"""Task C3: retrieval parent-expansion + citation-map invariant (offline).

_build_context_string / _parse_citations are pure functions; no DB/LLM. The
flag defaults off, so the flag-off tests also guard the byte-for-byte
compatibility of the current context string + positional citation resolution.
"""
from __future__ import annotations

import pytest

from taxflow.config import settings
from taxflow.services.agents.research import CONTEXT_TOKEN_LIMIT, ResearchAgent


@pytest.fixture
def agent():
    return ResearchAgent()


@pytest.fixture
def expansion_on(monkeypatch):
    monkeypatch.setattr(settings, "PARENT_EXPANSION_ENABLED", True)


def _child(cite, url, content, parent_key=None, parent_content=None, heading_path=None):
    return {
        "id": cite,
        "citation": cite,
        "source_url": url,
        "content": content,
        "parent_key": parent_key,
        "parent_content": parent_content,
        "heading_path": heading_path,
    }


# --- (a) two children share one parent -> single block + single map entry -----
def test_two_children_one_parent_collapse(agent, expansion_on):
    chunks = [
        _child("ITAA 1997 s 8-1", "http://x", "child A text",
               parent_key="http://x#s 8-1", parent_content="FULL SECTION 8-1 BODY",
               heading_path="ITAA 1997 > Division 8 > Section 8-1"),
        _child("ITAA 1997 s 8-1", "http://x", "child B text",
               parent_key="http://x#s 8-1", parent_content="FULL SECTION 8-1 BODY",
               heading_path="ITAA 1997 > Division 8 > Section 8-1"),
    ]
    context, citation_map = agent._build_context_string(chunks)
    # One rendered block, one citation_map entry, both children attached.
    assert len(citation_map) == 1
    assert context.count("[1]") == 1
    assert "[2]" not in context
    assert "FULL SECTION 8-1 BODY" in context
    # The parent body renders once, not the child text.
    assert "child A text" not in context
    assert len(citation_map[0]["chunks"]) == 2


# --- (b) citation mapping: two children of one parent + third chunk -----------
def test_citation_mapping_under_expansion(agent, expansion_on):
    chunks = [
        _child("ITAA 1997 s 8-1", "http://a", "child A",
               parent_key="http://a#s 8-1", parent_content="PARENT ONE"),
        _child("ITAA 1997 s 8-1", "http://a", "child B",
               parent_key="http://a#s 8-1", parent_content="PARENT ONE"),
        _child("TR 2024/1", "http://b", "independent chunk", parent_key=None),
    ]
    context, citation_map = agent._build_context_string(chunks)
    # Two rendered blocks: parent (collapsed) at [1], the third chunk at [2].
    assert len(citation_map) == 2
    # Model cites [1] and [2].
    citations = agent._parse_citations("See [1] and [2].", citation_map)
    by_cite = {c["citation"] for c in citations}
    assert by_cite == {"ITAA 1997 s 8-1", "TR 2024/1"}
    # [1] resolves to the parent's displayed source, [2] to the third chunk.
    first = next(c for c in citations if c["citation"] == "ITAA 1997 s 8-1")
    assert first["url"] == "http://a"
    second = next(c for c in citations if c["citation"] == "TR 2024/1")
    assert second["url"] == "http://b"


# --- (c) heading_path rendered ------------------------------------------------
def test_heading_path_rendered(agent, expansion_on):
    chunks = [
        _child("ITAA 1997 s 8-1", "http://x", "child",
               parent_key="http://x#s 8-1", parent_content="body",
               heading_path="ITAA 1997 > Division 8 > Section 8-1"),
    ]
    context, _ = agent._build_context_string(chunks)
    assert "ITAA 1997 > Division 8 > Section 8-1" in context


# --- (d) token-budget: expansion falls back to child once budget hit ----------
def test_token_budget_falls_back_to_child(agent, expansion_on):
    max_chars = CONTEXT_TOKEN_LIMIT * 4
    big_parent = "P" * (max_chars // 2 + 1000)  # two of these overflow the budget
    chunks = [
        _child("A", "http://a", "child A short",
               parent_key="http://a#1", parent_content=big_parent),
        _child("B", "http://b", "child B short",
               parent_key="http://b#1", parent_content=big_parent),
        _child("C", "http://c", "child C short",
               parent_key="http://c#1", parent_content=big_parent),
    ]
    context, citation_map = agent._build_context_string(chunks)
    # First parent expands; the rest fall back to child content.
    assert len(context) <= max_chars
    assert big_parent in context  # first parent rendered
    assert "child B short" in context  # second fell back to child
    assert "child C short" in context


def test_expansion_child_without_parent_uses_child(agent, expansion_on):
    chunks = [_child("Flat", "http://x", "flat content", parent_key=None)]
    context, citation_map = agent._build_context_string(chunks)
    assert "flat content" in context
    assert len(citation_map) == 1


# --- (d2) dedupe survives budget fallback -------------------------------------
def test_dedupe_of_rendered_parent_survives_budget_fallback(agent, expansion_on):
    """Parent P1 renders at [1]. A large parent P2 then trips the budget. A
    SECOND child of P1 must still collapse into [1] — not render a new block —
    even though ``budget_hit`` is now True."""
    max_chars = CONTEXT_TOKEN_LIMIT * 4
    big_parent = "P" * (max_chars + 1000)
    chunks = [
        # First child of P1: renders its (small) parent at [1].
        _child("ITAA 1997 s 8-1", "http://a", "child A1",
               parent_key="http://a#s 8-1", parent_content="SMALL PARENT ONE"),
        # Large parent P2: expanding it overflows the budget -> budget_hit=True,
        # falls back to child content at [2].
        _child("ITAA 1997 s 900", "http://b", "child B big",
               parent_key="http://b#s 900", parent_content=big_parent),
        # Second child of P1: budget is now hit, but it must still attach to [1].
        _child("ITAA 1997 s 8-1", "http://a", "child A2",
               parent_key="http://a#s 8-1", parent_content="SMALL PARENT ONE"),
    ]
    context, citation_map = agent._build_context_string(chunks)
    # Two rendered blocks only: [1] = P1 (collapsed), [2] = P2 child fallback.
    assert len(citation_map) == 2
    assert context.count("[1]") == 1
    assert context.count("[2]") == 1
    assert "[3]" not in context
    # P1 parent rendered once; both its children attached to the same entry.
    assert context.count("SMALL PARENT ONE") == 1
    assert len(citation_map[0]["chunks"]) == 2
    # P2 fell back to child content (budget hit).
    assert "child B big" in context
    assert big_parent not in context


# --- (e) flag off: byte-for-byte current context + positional resolution ------
def test_flag_off_matches_current_context_and_positional_citations(agent):
    assert settings.PARENT_EXPANSION_ENABLED is False
    chunks = [
        {"citation": "TR 2024/1", "source_url": "http://a", "content": "first source",
         "last_scraped_at": None},
        {"citation": "TR 2024/2", "source_url": "http://b", "content": "second source",
         "last_scraped_at": None},
    ]
    context, citation_map = agent._build_context_string(chunks)
    # Byte-for-byte the pre-C3 flat rendering.
    expected = (
        "[1] Citation: TR 2024/1\nSource: http://a\nContent: first source\n---\n"
        "[2] Citation: TR 2024/2\nSource: http://b\nContent: second source\n---"
    )
    assert context == expected
    # Positional resolution: one map entry per chunk in order.
    assert len(citation_map) == 2
    citations = agent._parse_citations("Cite [1] and [2].", citation_map)
    assert [c["citation"] for c in citations] == ["TR 2024/1", "TR 2024/2"]
    assert citations[0]["url"] == "http://a"
    assert citations[1]["url"] == "http://b"
