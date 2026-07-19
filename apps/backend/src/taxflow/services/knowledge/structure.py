"""Structure-aware splitter for AU-tax documents (Workstream C, Task C2).

Chunks legislation and ATO rulings/PCGs on their logical units (Part / Division /
Subdivision / Section / subsection for legislation; numbered paragraphs for
rulings) instead of a flat sentence-packing window, and records a heading
breadcrumb (``heading_path``) and leaf marker (``section_ref``) per unit so a
retrieved child can be expanded back to its parent section at answer time.

Design notes:
- Marker regex set is chosen by ``source_type`` (legislation vs ruling/PCG).
  When no markers are found we gracefully degrade to flat packing (one unit
  covering the whole document), so a document we can't parse structurally still
  chunks exactly as the flat path would.
- No vendor SDK, no DB, no network — pure text processing plus the shared
  tokenizer/sentence-packing helpers from ``pipeline`` (keeps the architecture
  gate green: this module lives in ``services/`` and adds no new coupling).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from taxflow.config import settings
from taxflow.providers import get_tokenizer
from taxflow.services.knowledge.pipeline import (
    SENTENCE_SPLIT,
    _pack_sentences,
    classify_topic,
)


@dataclass
class Unit:
    """One logical unit of a document (a Section, a numbered paragraph, ...)."""

    heading_path: str
    section_ref: str
    level: str
    body: str


@dataclass
class ChunkRecord:
    """One embeddable child chunk produced from a unit."""

    content: str  # child text with heading_path prepended (embed/FTS surface)
    heading_path: str
    section_ref: str
    parent_key: str
    parent_content: str  # full parent-unit body
    topic: str | None = None
    chunk_level: str = "child"
    meta: dict = field(default_factory=dict)


# --- marker regexes ----------------------------------------------------------
# Ordered by structural level so a heading breadcrumb can be assembled: a Part
# resets the current Division, a Division resets the current Section, etc. Each
# marker matches at the start of a line. ``level`` is the breadcrumb component
# name; ``ref`` is a short leaf marker (``s 8-1``, ``Division 7A``, ``para 15``).

# Legislation markers (ITAA-style): Part, Division, Subdivision, Section,
# subsection. Section numbers in the ITAA use a hyphenated form (e.g. 8-1).
_LEG_MARKERS: list[tuple[str, re.Pattern, str]] = [
    ("Part", re.compile(r"^\s*Part\s+([0-9A-Za-z\-]+)\b(.*)$", re.IGNORECASE), "part"),
    ("Division", re.compile(r"^\s*Division\s+([0-9A-Za-z\-]+)\b(.*)$", re.IGNORECASE), "division"),
    ("Subdivision", re.compile(r"^\s*Subdivision\s+([0-9A-Za-z\-]+)\b(.*)$", re.IGNORECASE), "subdivision"),
    ("Section", re.compile(r"^\s*Section\s+([0-9]+[0-9A-Za-z\-]*)\b(.*)$", re.IGNORECASE), "section"),
    # Bare section-number heading, e.g. "8-1  General deductions".
    ("Section", re.compile(r"^\s*([0-9]+\-[0-9A-Za-z]+)\s+(.*)$"), "section_bare"),
    # Subsection, e.g. "(1)  You can deduct ..." — composes with the enclosing
    # section so section_ref becomes ``s 8-1(1)``.
    ("Subsection", re.compile(r"^\s*\(([0-9]+[0-9A-Za-z]*)\)\s+(.*)$"), "subsection"),
]

# Ruling / PCG markers: numbered paragraphs, e.g. "15. The Commissioner ..." or
# "23.  Where a taxpayer ...". These are the atomic citable units of an ATO
# ruling.
_RULING_MARKERS: list[tuple[str, re.Pattern, str]] = [
    ("Paragraph", re.compile(r"^\s*([0-9]+)\.\s+(.*)$"), "paragraph"),
]

_LEGISLATION_TYPES = {"legislation"}
_RULING_TYPES = {"ato_ruling", "ato_determination", "ato_guide"}


def _markers_for(source_type: str | None) -> list[tuple[str, re.Pattern, str]]:
    if source_type in _LEGISLATION_TYPES:
        return _LEG_MARKERS
    if source_type in _RULING_TYPES:
        return _RULING_MARKERS
    # Court decisions / state rulings / unknown: try ruling-style numbered
    # paragraphs (common in judgments too); fall back to flat if none match.
    return _RULING_MARKERS


# Which breadcrumb levels are "containers" (reset lower levels) for legislation.
# ``subsection`` sits below ``section`` so a new section clears the previous
# subsection.
_LEVEL_ORDER = ["part", "division", "subdivision", "section", "subsection"]


def _match_marker(
    line: str, markers: list[tuple[str, re.Pattern, str]]
) -> tuple[str, str, str, str] | None:
    """Return (label, ref_number, heading_text, level) for the first matching
    marker on ``line``, else None."""
    for label, pattern, level in markers:
        m = pattern.match(line)
        if m:
            ref_number = m.group(1).strip()
            heading_text = (m.group(2) or "").strip() if m.lastindex and m.lastindex >= 2 else ""
            return label, ref_number, heading_text, level
    return None


def _section_ref(
    label: str, level: str, ref_number: str, section_num: str | None = None
) -> str:
    """Short leaf marker string, e.g. ``s 8-1``, ``s 8-1(1)``, ``Division 7A``,
    ``para 15``."""
    if level in ("section", "section_bare"):
        return f"s {ref_number}"
    if level == "subsection":
        # Compose with the enclosing section when known: ``s 8-1(1)``.
        if section_num:
            return f"s {section_num}({ref_number})"
        return f"({ref_number})"
    if level == "paragraph":
        return f"para {ref_number}"
    return f"{label} {ref_number}"


def parse_structure(text: str, source_type: str | None) -> list[Unit]:
    """Split ``text`` into logical :class:`Unit` blocks by AU-tax markers.

    Returns one Unit per marked unit, each carrying the heading breadcrumb
    accumulated from any enclosing container markers. When no markers are found
    the whole document is returned as a single flat Unit (graceful degradation).
    """
    markers = _markers_for(source_type)
    lines = text.splitlines()

    # Breadcrumb state for legislation container levels.
    breadcrumb: dict[str, str] = {}
    units: list[Unit] = []
    current: Unit | None = None
    preamble: list[str] = []
    # Ref number of the section currently in scope, so a subsection can compose
    # its leaf marker as ``s 8-1(1)``.
    current_section_num: str | None = None

    def _heading_path(leaf: str) -> str:
        parts = [breadcrumb[lvl] for lvl in _LEVEL_ORDER if lvl in breadcrumb and breadcrumb[lvl] != leaf]
        if leaf:
            parts.append(leaf)
        return " > ".join(parts)

    for line in lines:
        matched = _match_marker(line, markers)
        if matched is None:
            if current is not None:
                current.body += ("\n" if current.body else "") + line
            else:
                preamble.append(line)
            continue

        label, ref_number, heading_text, level = matched
        leaf_label = f"{label} {ref_number}".strip()

        # For legislation container levels, update the breadcrumb and reset all
        # lower levels so a new Division clears the previous Section, etc.
        if level == "subsection":
            # Subsections compose with the enclosing section: heading shows the
            # section leaf, section_ref becomes ``s 8-1(1)``.
            breadcrumb.pop("subsection", None)
            heading = _heading_path(breadcrumb.get("section", ""))
        elif level in _LEVEL_ORDER:
            idx = _LEVEL_ORDER.index(level)
            for lower in _LEVEL_ORDER[idx:]:
                breadcrumb.pop(lower, None)
            breadcrumb[level] = leaf_label
            heading = _heading_path(leaf_label)
            if level == "section":
                current_section_num = ref_number
        elif level == "section_bare":
            leaf_label = f"Section {ref_number}"
            breadcrumb.pop("subsection", None)
            breadcrumb["section"] = leaf_label
            heading = _heading_path(leaf_label)
            current_section_num = ref_number
        else:
            # Ruling paragraphs: flat sequence, no container nesting.
            heading = leaf_label

        section_ref = _section_ref(label, level, ref_number, current_section_num)
        # Start a new unit; its body begins with the heading line's own text.
        body_start = heading_text if heading_text else ""
        current = Unit(
            heading_path=heading,
            section_ref=section_ref,
            level=level,
            body=body_start,
        )
        units.append(current)

    if not units:
        # No markers matched: whole document is one flat unit.
        return [Unit(heading_path="", section_ref="", level="flat", body=text.strip())]

    # Any text before the first marker is preamble; if there's meaningful
    # preamble, keep it as a leading flat unit so nothing is dropped.
    preamble_text = "\n".join(preamble).strip()
    if preamble_text:
        units.insert(0, Unit(heading_path="", section_ref="", level="flat", body=preamble_text))

    # Trim unit bodies.
    for u in units:
        u.body = u.body.strip()
    return [u for u in units if u.body]


def _parent_key(source_url: str, unit: Unit, ordinal: int) -> str:
    """Stable key grouping all children of one unit within a source_url."""
    base = unit.section_ref or unit.heading_path or f"unit-{ordinal}"
    return f"{source_url}#{base}"


def hierarchical_chunk(text: str, metadata: dict) -> list[ChunkRecord]:
    """Produce child :class:`ChunkRecord`s for ``text`` under its structure.

    Per unit: if the unit body exceeds ``CHUNK_SIZE_TOKENS`` it is split into
    children by re-using the shared sentence-packing loop (so intra-unit packing
    matches the flat path); otherwise the whole unit is one child. Each child's
    ``content`` has the ``heading_path`` prepended for embed/FTS. ``classify_topic``
    is called per child.
    """
    source_type = metadata.get("source_type")
    source_url = metadata.get("url", metadata.get("source_url", ""))
    title = metadata.get("title", "")
    citation = metadata.get("citation", "")

    tokenizer = get_tokenizer()
    chunk_tokens = settings.CHUNK_SIZE_TOKENS
    overlap_tokens = settings.CHUNK_OVERLAP_TOKENS

    units = parse_structure(text, source_type)
    records: list[ChunkRecord] = []

    for ordinal, unit in enumerate(units):
        parent_key = _parent_key(source_url, unit, ordinal)
        parent_content = unit.body

        if tokenizer.count(unit.body) > chunk_tokens:
            sentences = SENTENCE_SPLIT.split(unit.body)
            child_bodies = _pack_sentences(sentences, chunk_tokens, overlap_tokens)
        else:
            child_bodies = [unit.body]

        for child_body in child_bodies:
            if not child_body.strip():
                continue
            if unit.heading_path:
                content = f"{unit.heading_path}\n{child_body}"
            else:
                content = child_body
            topic = classify_topic(title, citation, child_body)
            records.append(
                ChunkRecord(
                    content=content,
                    heading_path=unit.heading_path,
                    section_ref=unit.section_ref,
                    parent_key=parent_key,
                    parent_content=parent_content,
                    topic=topic,
                    chunk_level="child",
                )
            )

    return records
