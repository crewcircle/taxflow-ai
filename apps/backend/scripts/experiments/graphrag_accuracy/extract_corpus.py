"""Step 1: pull the subset of the real knowledge base relevant to the 30
accuracy-suite questions, reconstruct documents from knowledge_chunks rows,
and write them as local .md files for LightRAG/Cognee to index.

Read-only against the real DB (only SELECTs) - never writes to knowledge_chunks
or any other production table. Run against --config prd since that's where the
real knowledge base lives (confirmed: 12,432 chunks / 615 documents there vs.
an empty throwaway --config dev DB).

Two ways a document earns a spot in the corpus:
1. It's in the top-N candidates the CURRENT pipeline's own generate_candidates()
   retrieves for one of the 30 questions (cheap, no LLM - pure RRF).
2. Its `citation` column loosely matches one of the questions' expected_citations
   labels - included even if current retrieval MISSES it, so LightRAG/Cognee get
   a fair chance to find something the baseline doesn't (excluding it here would
   bias the comparison toward "can graph-RAG re-rank what baseline already
   found", not "can it find what baseline misses").

Size cap: a handful of source documents are entire pieces of legislation (the
whole ITAA 1997 is 8.6M characters across its chunks) - reconstructing those in
full would blow the experiment's LLM-extraction cost/time budget by 10x+ for
one document. Anything over MAX_FULL_DOC_CHARS falls back to ONLY the specific
chunks that were actually retrieved/matched for these 30 questions (still
capped at MAX_PARTIAL_DOC_CHARS), instead of the entire Act.

Run: doppler run --project taxflow --config prd -- \\
     uv run python scripts/experiments/graphrag_accuracy/extract_corpus.py
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))

from taxflow.services.knowledge.retrieval import generate_candidates  # noqa: E402
from taxflow.db import get_pg_conn  # noqa: E402

HERE = os.path.dirname(__file__)
QUESTIONS_PATH = os.path.join(HERE, "..", "..", "..", "tests", "accuracy", "questions.json")
CORPUS_DIR = os.path.join(HERE, "corpus")
MANIFEST_PATH = os.path.join(HERE, "manifest.json")

CANDIDATES_PER_QUESTION = 15
MAX_FULL_DOC_CHARS = 150_000
MAX_PARTIAL_DOC_CHARS = 60_000


def _slugify(url: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", url).strip("_")[:120]


async def _relevant_chunks_from_retrieval(questions: list[dict]) -> dict[str, dict[int, str]]:
    """url -> {chunk_index: content} for every chunk that showed up as a
    retrieval candidate for one of the 30 questions."""
    by_url: dict[str, dict[int, str]] = {}
    for q in questions:
        candidates = await generate_candidates(q["question"])
        for c in candidates[:CANDIDATES_PER_QUESTION]:
            url = c.get("source_url")
            if not url:
                continue
            by_url.setdefault(url, {})
            # generate_candidates doesn't carry chunk_index, only content - key
            # on content itself as a de-dup proxy (fine for our fallback path,
            # which just needs SOME representative chunks, not exact ordering).
            by_url[url][hash(c["content"])] = c["content"]
        print(f"  [{q['id']}] retrieval -> {len(candidates[:CANDIDATES_PER_QUESTION])} candidate urls")
    return by_url


def _relevant_chunks_from_citation_labels(questions: list[dict]) -> dict[str, dict[int, str]]:
    labels: set[str] = set()
    for q in questions:
        labels.update(q.get("expected_citations", []))

    by_url: dict[str, dict[int, str]] = {}
    with get_pg_conn() as conn:
        cur = conn.cursor()
        for label in labels:
            cur.execute(
                """
                SELECT source_url, chunk_index, content FROM knowledge_chunks
                WHERE citation ILIKE %s ORDER BY source_url, chunk_index LIMIT 100
                """,
                (f"%{label}%",),
            )
            for url, chunk_index, content in cur.fetchall():
                by_url.setdefault(url, {})[chunk_index] = content
    print(f"  citation-label match -> {len(by_url)} additional/overlapping urls across {len(labels)} labels")
    return by_url


def _merge_chunk_maps(a: dict[str, dict], b: dict[str, dict]) -> dict[str, dict]:
    merged = {url: dict(chunks) for url, chunks in a.items()}
    for url, chunks in b.items():
        merged.setdefault(url, {}).update(chunks)
    return merged


def _reconstruct_documents(relevant_chunks: dict[str, dict]) -> list[dict]:
    """For each url: try the FULL document (all its chunks, in chunk_index
    order) if that's under MAX_FULL_DOC_CHARS; otherwise fall back to only the
    chunks that were actually retrieved/matched for these questions, capped at
    MAX_PARTIAL_DOC_CHARS."""
    if not relevant_chunks:
        return []
    docs = []
    with get_pg_conn() as conn:
        cur = conn.cursor()
        for url in sorted(relevant_chunks):
            cur.execute(
                """
                SELECT source_title, citation, source_type, content, char_length(content)
                FROM knowledge_chunks WHERE source_url = %s ORDER BY chunk_index
                """,
                (url,),
            )
            rows = cur.fetchall()
            if not rows:
                continue
            title, citation, source_type = rows[0][0], rows[0][1], rows[0][2]
            full_len = sum(r[4] for r in rows)

            if full_len <= MAX_FULL_DOC_CHARS:
                text = "\n\n".join(r[3] for r in rows)
                mode = "full"
            else:
                # Fallback: only the relevant chunks for this url, capped.
                pieces = list(relevant_chunks[url].values())
                text = ""
                for piece in pieces:
                    if len(text) + len(piece) > MAX_PARTIAL_DOC_CHARS:
                        break
                    text += piece + "\n\n"
                mode = f"partial({len(pieces)} of {len(rows)} chunks)"

            docs.append(
                {
                    "source_url": url,
                    "title": title,
                    "citation": citation,
                    "source_type": source_type,
                    "chunk_count": len(rows),
                    "char_count": len(text),
                    "mode": mode,
                    "text": text,
                }
            )
    return docs


async def main() -> None:
    questions = json.loads(open(QUESTIONS_PATH).read())
    print(f"Loaded {len(questions)} accuracy-suite questions")

    print("Retrieving current-pipeline candidate chunks per question...")
    retrieval_chunks = await _relevant_chunks_from_retrieval(questions)

    print("Matching expected_citations labels against knowledge_chunks.citation...")
    label_chunks = _relevant_chunks_from_citation_labels(questions)

    relevant = _merge_chunk_maps(retrieval_chunks, label_chunks)
    print(f"Total distinct source documents in corpus: {len(relevant)}")

    docs = _reconstruct_documents(relevant)

    os.makedirs(CORPUS_DIR, exist_ok=True)
    manifest = []
    for doc in docs:
        filename = f"{_slugify(doc['source_url'])}.md"
        path = os.path.join(CORPUS_DIR, filename)
        with open(path, "w") as f:
            f.write(f"# {doc['title']}\n\nCitation: {doc['citation']}\n\n{doc['text']}")
        manifest.append(
            {
                "filename": filename,
                "source_url": doc["source_url"],
                "title": doc["title"],
                "citation": doc["citation"],
                "source_type": doc["source_type"],
                "chunk_count": doc["chunk_count"],
                "char_count": doc["char_count"],
                "mode": doc["mode"],
            }
        )
        if doc["mode"] != "full":
            print(f"  capped: {doc['citation']} -> {doc['mode']}, {doc['char_count']:,} chars")

    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)

    total_chars = sum(m["char_count"] for m in manifest)
    print(f"\nWrote {len(manifest)} documents to {CORPUS_DIR} ({total_chars:,} chars total)")
    print(f"Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
