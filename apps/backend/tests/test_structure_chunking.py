"""Task C2: structure-aware splitter + hierarchical ingest (offline).

parse_structure / hierarchical_chunk are pure text processing (real tiktoken
tokenizer, no DB/LLM/network). The flat-mode guard test patches
embed_batch/_upsert_chunks like test_pipeline_supersede.py so no embedding or DB
call happens.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from taxflow.config import settings
from taxflow.services.knowledge import pipeline
from taxflow.services.knowledge.pipeline import chunk_text
from taxflow.services.knowledge.structure import (
    hierarchical_chunk,
    parse_structure,
)

# --- fixtures ----------------------------------------------------------------
ACT_EXCERPT = """Division 8 Deductions

Section 8-1 General deductions
You can deduct from your assessable income any loss or outgoing to the extent
that it is incurred in gaining or producing your assessable income. However,
you cannot deduct a loss or outgoing that is of a capital nature.

Section 8-5 Specific deductions
You can also deduct from your assessable income an amount that a provision of
this Act allows you to deduct. Some provisions prevent you from deducting an
amount that you could otherwise deduct, or limit the amount you can deduct.
"""

RULING_EXCERPT = """This Ruling explains the Commissioner's view.

1. This Ruling sets out when a payment is assessable income of the recipient.
It applies to payments made on or after 1 July 2024 to Australian residents.

2. The Commissioner considers that a payment is ordinary income where it is a
product of services rendered. This includes salary, wages and commissions.

3. A payment that is a mere gift is not ordinary income and is not assessable
under section 6-5 of the ITAA 1997.
"""

SUBSECTION_EXCERPT = """Section 8-1 General deductions

(1) You can deduct from your assessable income any loss or outgoing to the
extent that it is incurred in gaining or producing your assessable income.

(2) However, you cannot deduct a loss or outgoing under this section to the
extent that it is a loss or outgoing of capital, or of a capital nature.
"""


# --- parse_structure ---------------------------------------------------------
def test_parse_structure_legislation_two_sections():
    units = parse_structure(ACT_EXCERPT, "legislation")
    # Division heading + its own two Sections = 3 marked units (Division block
    # may be body-less and dropped if empty; the two Sections must be present).
    section_units = [u for u in units if u.level in ("section", "section_bare")]
    assert len(section_units) == 2
    refs = {u.section_ref for u in section_units}
    assert refs == {"s 8-1", "s 8-5"}
    # Breadcrumb carries the enclosing Division.
    for u in section_units:
        assert u.heading_path.startswith("Division 8")
        assert u.heading_path.endswith(u.section_ref.replace("s ", "Section "))


def test_parse_structure_ruling_numbered_paragraphs():
    units = parse_structure(RULING_EXCERPT, "ato_ruling")
    para_units = [u for u in units if u.level == "paragraph"]
    assert len(para_units) == 3
    assert [u.section_ref for u in para_units] == ["para 1", "para 2", "para 3"]
    # No paragraph body bleeds into the next.
    assert "product of services" in para_units[1].body
    assert "product of services" not in para_units[0].body
    assert "mere gift" in para_units[2].body


def test_parse_structure_legislation_subsections():
    units = parse_structure(SUBSECTION_EXCERPT, "legislation")
    sub_units = [u for u in units if u.level == "subsection"]
    # Two subsections under s 8-1, each composing with the section number.
    assert [u.section_ref for u in sub_units] == ["s 8-1(1)", "s 8-1(2)"]
    # Heading breadcrumb points back at the enclosing section.
    for u in sub_units:
        assert "Section 8-1" in u.heading_path
    # Bodies stay in their own subsection.
    assert "incurred in gaining" in sub_units[0].body
    assert "incurred in gaining" not in sub_units[1].body
    assert "capital" in sub_units[1].body


def test_hierarchical_chunk_subsection_section_ref():
    records = hierarchical_chunk(SUBSECTION_EXCERPT, _meta())
    refs = {r.section_ref for r in records}
    assert "s 8-1(1)" in refs
    assert "s 8-1(2)" in refs


def test_parse_structure_no_markers_falls_back_to_flat():
    text = "Just some prose with no headings at all. Another sentence here."
    units = parse_structure(text, "legislation")
    assert len(units) == 1
    assert units[0].level == "flat"
    assert units[0].heading_path == ""


# --- hierarchical_chunk ------------------------------------------------------
def _meta():
    return {
        "source_type": "legislation",
        "url": "https://legislation.example/itaa1997",
        "title": "ITAA 1997",
        "citation": "ITAA 1997",
        "jurisdiction": "federal",
    }


def test_hierarchical_chunk_boundaries_align_to_sections():
    records = hierarchical_chunk(ACT_EXCERPT, _meta())
    # Each record belongs to exactly one section: no record contains text from
    # both sections.
    for r in records:
        has_81 = "8-1" in r.section_ref or "loss or outgoing" in r.content
        has_85 = "8-5" in r.section_ref
        assert not (r.section_ref == "s 8-1" and "Specific deductions" in r.content)
    # Two sections -> at least two parent_keys.
    parent_keys = {r.parent_key for r in records}
    assert len(parent_keys) >= 2


def test_hierarchical_chunk_heading_prepended_and_section_ref():
    records = hierarchical_chunk(ACT_EXCERPT, _meta())
    s81 = [r for r in records if r.section_ref == "s 8-1"]
    assert s81
    for r in s81:
        assert r.content.startswith(r.heading_path)
        assert "Division 8" in r.heading_path
        assert r.chunk_level == "child"


def test_hierarchical_chunk_children_share_parent_key_and_content():
    # Force a small chunk size so the one section splits into multiple children.
    long_body = " ".join(f"Sentence number {i} about deductions." for i in range(200))
    text = f"Section 8-1 General deductions\n{long_body}"
    meta = _meta()
    original = settings.CHUNK_SIZE_TOKENS
    try:
        settings.CHUNK_SIZE_TOKENS = 40
        records = hierarchical_chunk(text, meta)
    finally:
        settings.CHUNK_SIZE_TOKENS = original
    s81 = [r for r in records if r.section_ref == "s 8-1"]
    assert len(s81) >= 2  # split into multiple children
    parent_keys = {r.parent_key for r in s81}
    parent_contents = {r.parent_content for r in s81}
    assert len(parent_keys) == 1
    assert len(parent_contents) == 1


# --- flat-mode guard ---------------------------------------------------------
@pytest.mark.asyncio
async def test_flat_mode_matches_chunk_text():
    """Flag OFF: process_document chunk texts equal today's chunk_text(text)
    verbatim (guards the _pack_sentences extraction)."""
    text = (
        "The first sentence explains the deduction rule. The second sentence "
        "gives an example of a capital outgoing. A third sentence clarifies "
        "the timing of the deduction. And a fourth wraps up the point."
    )
    expected = chunk_text(text)
    metadata = {
        "source_type": "legislation",
        "url": "https://legislation.example/x",
        "title": "T",
        "citation": "C",
        "jurisdiction": "federal",
    }

    captured = {}

    def fake_upsert(rows):
        captured["rows"] = rows
        return len(rows)

    assert settings.HIERARCHICAL_CHUNKING_ENABLED is False
    with patch(
        "taxflow.services.knowledge.pipeline.embed_batch",
        new=AsyncMock(side_effect=lambda chunks: [[0.0] for _ in chunks]),
    ), patch("taxflow.services.knowledge.pipeline._upsert_chunks", side_effect=fake_upsert), patch(
        "taxflow.services.knowledge.pipeline._detect_superseded_citations", return_value=set()
    ):
        await pipeline.process_document(text, metadata)

    rows = captured["rows"]
    # Column 4 (0-based index 4) is the chunk content in the row tuple.
    row_contents = [r[4] for r in rows]
    assert row_contents == expected
    # Flat mode marks chunk_level='flat' and NULLs hierarchy fields.
    for r in rows:
        assert r[12] is None  # heading_path
        assert r[13] is None  # section_ref
        assert r[14] == "flat"  # chunk_level
        assert r[15] is None  # parent_key
        assert r[16] is None  # parent_content
