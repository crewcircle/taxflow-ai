import asyncio
import json
import re

import psycopg2.extras

from taxflow.config import settings
from taxflow.db import get_pg_conn
from taxflow.services.knowledge.embedder import embed

# --- Lightweight query normalisation (Task C1) --------------------------------
# Cheap, deterministic, no LLM: normalise common Australian tax section-number
# formats and a few high-value synonyms before search so the text search / RRF
# candidate pool aligns with how sources phrase things. Low risk: purely
# additive text tweaks, gated by QUERY_NORMALISE_ENABLED.
_SECTION_PATTERN = re.compile(r"\bs(?:ec|ection)?\.?\s*(\d+[A-Za-z]?(?:-\d+)?)\b", re.IGNORECASE)
_SYNONYMS = {
    "cgt": "capital gains tax",
    "gst": "goods and services tax",
    "fbt": "fringe benefits tax",
    "pbr": "private binding ruling",
    "itaa": "Income Tax Assessment Act",
}


def normalise_query(query: str) -> str:
    """Normalise section numbers and expand a few synonyms (Task C1).

    e.g. "s8-1" / "sec 8-1" -> "section 8-1"; "CGT" -> "CGT capital gains tax".
    Returns the query unchanged when QUERY_NORMALISE_ENABLED is False.
    """
    if not settings.QUERY_NORMALISE_ENABLED:
        return query
    normalised = _SECTION_PATTERN.sub(lambda m: f"section {m.group(1)}", query)
    for abbr, expansion in _SYNONYMS.items():
        if re.search(rf"\b{re.escape(abbr)}\b", normalised, re.IGNORECASE):
            normalised = f"{normalised} {expansion}"
    return normalised


def _semantic_search(embedding: list[float], source_types: list[str] | None, limit: int) -> list[dict]:
    with get_pg_conn() as conn:
        # SET LOCAL only applies inside an explicit transaction; on a pooled
        # connection a bare SET LOCAL outside a transaction silently no-ops. The
        # psycopg2 connection context manager opens/commits one transaction, so we
        # scope the probes tuning and the vector SELECT together here.
        with conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SET LOCAL ivfflat.probes = %s", (settings.IVFFLAT_PROBES,))
            cur.execute(
                """
                SELECT id, citation, content, source_url, source_object_key, source_type,
                       1 - (embedding <=> %s::vector) AS cosine_sim
                FROM knowledge_chunks
                WHERE is_current = true
                  AND (%s::text[] IS NULL OR source_type = ANY(%s))
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (embedding, source_types, source_types, embedding, limit),
            )
            rows = cur.fetchall()
            cur.close()
            return list(rows)


def _text_search(query: str, source_types: list[str] | None, limit: int) -> list[dict]:
    with get_pg_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT id, citation, content, source_url, source_object_key, source_type,
                   ts_rank(to_tsvector('english', content), plainto_tsquery('english', %s)) AS text_rank
            FROM knowledge_chunks
            WHERE is_current = true
              AND to_tsvector('english', content) @@ plainto_tsquery('english', %s)
              AND (%s::text[] IS NULL OR source_type = ANY(%s))
            ORDER BY text_rank DESC
            LIMIT %s
            """,
            (query, query, source_types, source_types, limit),
        )
        rows = cur.fetchall()
        cur.close()
        return list(rows)


def _rrf_merge(semantic: list[dict], textual: list[dict]) -> list[dict]:
    """Reciprocal-rank-fusion merge of the semantic + text candidate lists.

    RRF is a cheap candidate generator (Task C1): it never calls an LLM. Returns
    candidates sorted by fused score, carrying the score on each dict.
    """
    scores: dict[str, float] = {}
    docs: dict[str, dict] = {}
    for rank, row in enumerate(semantic):
        scores[row["id"]] = scores.get(row["id"], 0.0) + 1 / (60 + rank)
        docs[row["id"]] = row
    for rank, row in enumerate(textual):
        scores[row["id"]] = scores.get(row["id"], 0.0) + 1 / (60 + rank)
        docs.setdefault(row["id"], row)

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [
        {
            "id": doc_id,
            "citation": docs[doc_id]["citation"],
            "content": docs[doc_id]["content"],
            "source_url": docs[doc_id]["source_url"],
            "source_object_key": docs[doc_id].get("source_object_key"),
            "source_type": docs[doc_id].get("source_type"),
            "score": score,
        }
        for doc_id, score in ranked
    ]


async def _llm_rerank(query: str, candidates: list[dict]) -> list[dict]:
    """Re-order candidates with ONE batched Haiku relevance-scoring call (Task C1).

    Only invoked when RERANK_MODE == "llm". Sends the top RERANK_DEPTH candidates
    to a single cheap-model call that returns a relevance score per candidate; we
    re-order by that score and store it as `rerank_score`. A single Anthropic call
    over the whole batch — never one call per candidate. On any failure we fall
    back to the input order so retrieval never breaks over the re-rank.
    """
    # Imported lazily so "off"/"rrf_only" paths never import the Anthropic client.
    from anthropic import AsyncAnthropic

    depth = min(len(candidates), settings.RERANK_DEPTH)
    if depth == 0:
        return candidates
    batch = candidates[:depth]

    listing = "\n".join(
        f"[{i}] {c['citation']}: {c['content'][:500]}" for i, c in enumerate(batch)
    )
    system = (
        "You are a retrieval re-ranker for Australian tax law. Score how relevant "
        "each candidate passage is to the user's question from 0.0 (irrelevant) to "
        "1.0 (directly answers it). Return ONLY a JSON object mapping the candidate "
        'index (as a string) to its score, e.g. {"0": 0.9, "1": 0.2}. No prose.'
    )
    user = f"Question: {query}\n\nCandidates:\n{listing}"

    client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    try:
        response = await client.messages.create(
            model=settings.ANTHROPIC_HAIKU_MODEL,
            max_tokens=500,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(block.text for block in response.content if block.type == "text").strip()
        scores = _extract_scores(text, depth)
    except Exception:  # noqa: BLE001 - never fail retrieval over the re-rank
        return candidates

    for i, cand in enumerate(batch):
        cand["rerank_score"] = scores.get(i, 0.0)
    reranked = sorted(batch, key=lambda c: c.get("rerank_score", 0.0), reverse=True)
    # Candidates beyond the re-rank depth keep their RRF order, appended after.
    return reranked + candidates[depth:]


def _extract_scores(text: str, depth: int) -> dict[int, float]:
    """Tolerantly parse the {index: score} JSON from the re-ranker output."""
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0].strip()
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return {}
        try:
            raw = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
    out: dict[int, float] = {}
    for k, v in raw.items():
        try:
            idx = int(k)
            if 0 <= idx < depth:
                out[idx] = float(v)
        except (ValueError, TypeError):
            continue
    return out


def apply_source_type_boost(candidates: list[dict], boost_types: list[str] | None) -> list[dict]:
    """SOFT BOOST matching source_types (Task D2). Never excludes anything.

    Multiplies the RRF `score` of candidates whose `source_type` is in
    boost_types by (1 + SOURCE_TYPE_BOOST_WEIGHT) and re-sorts. The candidate
    pool is left intact — a non-matching doc keeps its score and stays
    retrievable, so we can never drop the one relevant doc (unlike a hard SQL
    filter). No-op when boost_types is empty or the weight is 0. Returns a
    re-sorted list; mutates each candidate's `score` in place.
    """
    if not boost_types or settings.SOURCE_TYPE_BOOST_WEIGHT <= 0:
        return candidates
    boost_set = set(boost_types)
    multiplier = 1.0 + settings.SOURCE_TYPE_BOOST_WEIGHT
    for cand in candidates:
        if cand.get("source_type") in boost_set:
            cand["score"] = cand.get("score", 0.0) * multiplier
    return sorted(candidates, key=lambda c: c.get("score", 0.0), reverse=True)


async def generate_candidates(
    query: str,
    source_types: list[str] | None = None,
    embedding: list[float] | None = None,
) -> list[dict]:
    """RRF candidate generation over a widened pool (Task C1). NEVER calls an LLM.

    Returns the merged RRF candidates (untruncated, unranked beyond RRF) so a
    caller can merge in other candidates (e.g. firm chunks, Task C4) and re-rank
    the combined pool together.
    """
    if embedding is None:
        embedding = await embed(query)

    text_query = normalise_query(query)
    pool = settings.RERANK_CANDIDATE_POOL
    semantic, textual = await asyncio.gather(
        asyncio.to_thread(_semantic_search, embedding, source_types, pool),
        asyncio.to_thread(_text_search, text_query, source_types, pool),
    )
    return _rrf_merge(semantic, textual)


async def rerank_candidates(query: str, candidates: list[dict]) -> list[dict]:
    """Apply RERANK_MODE to an already-merged candidate list (Task C1).

    "off"/"rrf_only" return the candidates unchanged (NO LLM call). "llm" runs a
    single batched Haiku relevance-scoring call and re-orders by score.
    """
    if settings.RERANK_MODE == "llm":
        return await _llm_rerank(query, candidates)
    return candidates


async def hybrid_search(
    query: str,
    top_k: int = 10,
    source_types: list[str] | None = None,
    embedding: list[float] | None = None,
) -> list[dict]:
    """Hybrid retrieval: RRF candidate generation + optional re-rank (Task C1).

    RRF is always the candidate generator over a widened pool
    (RERANK_CANDIDATE_POOL each). RERANK_MODE then decides post-processing:
      - "off"/"rrf_only": merge by RRF, take top_k. NO LLM call.
      - "llm": one batched Haiku relevance-scoring call re-orders the merged
        candidates before truncation.
    Each returned chunk carries `score` (RRF) and, in llm mode, `rerank_score`.
    """
    candidates = await generate_candidates(query, source_types=source_types, embedding=embedding)
    candidates = await rerank_candidates(query, candidates)
    return candidates[:top_k]
