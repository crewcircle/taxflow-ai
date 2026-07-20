import asyncio
import logging
import re

import tiktoken

from taxflow.config import settings
from taxflow.providers import get_relational_data, get_tokenizer
from taxflow.services.knowledge.embedder import embed_batch

logger = logging.getLogger(__name__)

_encoder = tiktoken.get_encoding("cl100k_base")

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# ATO rulings often name the specific ruling they replace in their own preamble
# (e.g. "This Ruling replaces TR 2020/4"). When a newly-ingested document says
# so explicitly, mark the referenced ruling is_current = false so retrieval
# stops surfacing it as if it were still authoritative. This only catches
# direct citation-to-citation supersession, not conceptual replacement (e.g.
# "the third-party debt test replaces the arm's length debt test" names a
# concept, not a ruling number) - those still need a human to flag.
_SUPERSESSION_PATTERNS = [
    re.compile(
        r"(?:replaces?|withdraws?|supersedes?)\s+(?:Taxation Ruling|Taxation Determination|"
        r"Practical Compliance Guideline)?\s*((?:TR|TD|PCG)\s?\d{4}/\d+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"((?:TR|TD|PCG)\s?\d{4}/\d+)\s+(?:is|was|has been)\s+(?:withdrawn|replaced|superseded)",
        re.IGNORECASE,
    ),
]


def _detect_superseded_citations(text: str) -> set[str]:
    found: set[str] = set()
    for pattern in _SUPERSESSION_PATTERNS:
        for match in pattern.finditer(text):
            citation = re.sub(r"\s+", " ", match.group(1).upper()).strip()
            citation = re.sub(r"^(TR|TD|PCG)(\d)", r"\1 \2", citation)
            found.add(citation)
    return found


def _mark_superseded(mapping: dict[str, str]) -> int:
    return get_relational_data().knowledge_ingest.mark_superseded(mapping)


# Phase 3: lightweight, deterministic topic classification for the knowledge
# graph explorer - not retrieval-critical (never filters/boosts search), so a
# cheap keyword match beats an LLM call here. Checked in order, first match
# wins; the vocabulary matches the demo persona scenario tags already used
# elsewhere in the product (seed_demo.py topic_tag values) plus the newer
# source areas (payroll tax, duties/land tax, superannuation) Phase 2 added.
_TOPICS: list[tuple[str, re.Pattern]] = [
    ("Division 7A", re.compile(r"division 7a|deemed dividend", re.IGNORECASE)),
    ("Thin capitalisation", re.compile(r"thin capitalisation|debt deduction creation", re.IGNORECASE)),
    (
        "Trust distributions",
        re.compile(r"present entitlement|reimbursement agreement|division 6\b|trust distribution", re.IGNORECASE),
    ),
    ("CGT concessions", re.compile(r"capital gains tax|cgt discount|small business cgt", re.IGNORECASE)),
    ("GST margin scheme", re.compile(r"margin scheme", re.IGNORECASE)),
    ("R&D tax incentive", re.compile(r"research and development tax incentive|r&d tax offset", re.IGNORECASE)),
    ("FBT car benefits", re.compile(r"car benefit|fringe benefits tax|\bfbt\b", re.IGNORECASE)),
    ("Work-from-home deductions", re.compile(r"work[- ]from[- ]home|home office", re.IGNORECASE)),
    ("Superannuation", re.compile(r"superannuation guarantee|super contribution", re.IGNORECASE)),
    ("Payroll tax", re.compile(r"payroll tax", re.IGNORECASE)),
    ("Stamp duty / land tax", re.compile(r"stamp duty|transfer duty|land tax|dutiable transaction", re.IGNORECASE)),
    ("Equipment finance", re.compile(r"equipment finance|hire purchase|chattel mortgage", re.IGNORECASE)),
    ("GST", re.compile(r"goods and services tax|\bgst\b", re.IGNORECASE)),
]


def classify_topic(title: str, citation: str, text: str) -> str | None:
    """Classified per CHUNK, not per document: a focused ruling is topically
    uniform throughout so this makes no difference there, but a whole Act
    (one citation, thousands of chunks covering every topic it legislates)
    would otherwise get one meaningless topic guessed from its title page."""
    sample = f"{title} {citation} {text}"
    for topic, pattern in _TOPICS:
        if pattern.search(sample):
            return topic
    return None


def _pack_sentences(
    sentences: list[str], chunk_tokens: int, overlap_tokens: int
) -> list[str]:
    """Sentence-packing loop shared by flat ``chunk_text`` and the intra-unit
    child split in ``structure.hierarchical_chunk`` (Workstream C).

    Packs sentences into ~``chunk_tokens`` segments at sentence boundaries,
    carrying ``overlap_tokens`` of trailing sentences into the next segment.
    Extracting this from ``chunk_text`` means flat and hierarchical modes share
    ONE implementation, so a child split inside one section produces identical
    packing to the flat path.
    """
    tokenizer = get_tokenizer()
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for sentence in sentences:
        sentence_tokens = tokenizer.count(sentence)
        if current and current_tokens + sentence_tokens > chunk_tokens:
            chunks.append(" ".join(current))
            # Carry overlap: keep trailing sentences up to overlap_tokens
            kept: list[str] = []
            kept_tokens = 0
            for s in reversed(current):
                s_tokens = tokenizer.count(s)
                if kept_tokens + s_tokens > overlap_tokens:
                    break
                kept.insert(0, s)
                kept_tokens += s_tokens
            current = kept
            current_tokens = kept_tokens
        current.append(sentence)
        current_tokens += sentence_tokens

    if current:
        chunks.append(" ".join(current))
    return [c.strip() for c in chunks if c.strip()]


def chunk_text(text: str, chunk_tokens: int | None = None, overlap_tokens: int | None = None) -> list[str]:
    """Split into ~chunk_tokens segments at sentence boundaries with token overlap."""
    chunk_tokens = chunk_tokens or settings.CHUNK_SIZE_TOKENS
    overlap_tokens = overlap_tokens or settings.CHUNK_OVERLAP_TOKENS

    sentences = SENTENCE_SPLIT.split(text)
    return _pack_sentences(sentences, chunk_tokens, overlap_tokens)


def _upsert_chunks(rows: list[tuple]) -> int:
    return get_relational_data().knowledge_ingest.upsert_chunks(rows)


async def process_document(text: str, metadata: dict, source_object_key: str | None = None) -> int:
    """Chunk, embed, and upsert one document. Returns chunk count.

    Two modes, gated by ``settings.HIERARCHICAL_CHUNKING_ENABLED``:
    - flat (default / flag off): today's exact behaviour — ``chunk_text`` splits
      on a sentence-packing window, rows carry ``chunk_level='flat'`` and NULL
      for the hierarchy fields.
    - hierarchical (flag on): ``structure.hierarchical_chunk`` splits on logical
      units with heading breadcrumbs; rows carry ``chunk_level='child'`` plus
      heading_path/section_ref/parent_key/parent_content.
    Both modes build the same 17-column row tuple, so ONE upsert path serves both.
    """
    if settings.HIERARCHICAL_CHUNKING_ENABLED:
        rows = await _hierarchical_rows(text, metadata, source_object_key)
    else:
        rows = await _flat_rows(text, metadata, source_object_key)

    if not rows:
        return 0

    chunk_count = await asyncio.to_thread(_upsert_chunks, rows)

    superseded = _detect_superseded_citations(text) - {metadata["citation"]}
    if superseded:
        mapping = {old: metadata["citation"] for old in superseded}
        marked = await asyncio.to_thread(_mark_superseded, mapping)
        if marked:
            logger.info("%s marks %s as superseded (%d chunks)", metadata['citation'], superseded, marked)

    return chunk_count


async def _flat_rows(text: str, metadata: dict, source_object_key: str | None) -> list[tuple]:
    """Build flat-mode row tuples (chunk_level='flat', hierarchy fields None)."""
    chunks = chunk_text(text)
    if not chunks:
        return []

    embeddings = await embed_batch(chunks)

    return [
        (
            metadata["source_type"],
            metadata["url"],
            metadata["title"],
            metadata["citation"],
            chunk,
            embedding,
            index,
            len(_encoder.encode(chunk)),
            metadata.get("effective_date"),
            source_object_key,
            metadata.get("jurisdiction"),
            classify_topic(metadata["title"], metadata["citation"], chunk),
            None,  # heading_path (flat mode)
            None,  # section_ref (flat mode)
            "flat",  # chunk_level
            None,  # parent_key (flat mode)
            None,  # parent_content (flat mode)
        )
        for index, (chunk, embedding) in enumerate(zip(chunks, embeddings))
    ]


async def _hierarchical_rows(text: str, metadata: dict, source_object_key: str | None) -> list[tuple]:
    """Build hierarchical-mode row tuples from structure-aware child chunks."""
    # Imported lazily to avoid a circular import (structure imports from pipeline).
    from taxflow.services.knowledge.structure import hierarchical_chunk

    records = hierarchical_chunk(text, metadata)
    if not records:
        return []

    embeddings = await embed_batch([r.content for r in records])

    return [
        (
            metadata["source_type"],
            metadata["url"],
            metadata["title"],
            metadata["citation"],
            record.content,
            embedding,
            index,
            len(_encoder.encode(record.content)),
            metadata.get("effective_date"),
            source_object_key,
            metadata.get("jurisdiction"),
            record.topic,
            record.heading_path or None,
            record.section_ref or None,
            record.chunk_level,
            record.parent_key,
            record.parent_content,
        )
        for index, (record, embedding) in enumerate(zip(records, embeddings))
    ]
