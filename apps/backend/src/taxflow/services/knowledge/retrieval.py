import asyncio
import json
import re

from taxflow import providers
from taxflow.config import settings
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


# --- Recency tie-breaker (from main) ------------------------------------------
_YEAR_RE = re.compile(r"(19|20)\d{2}")

# Small nudge, not a sledgehammer: a single RRF term at rank 0 is ~1/60 = 0.0167,
# so 0.0006/year means a document ~10 years newer gains roughly one rank-step of
# priority over an equally-relevant older one - enough to break ties between two
# rulings on the same topic (e.g. a 2020 and a 2025 ruling covering the same
# provision) without letting recency override a genuinely better semantic/text
# match. Documents whose citation has no parseable year (legislation, firm
# knowledge) get a neutral mid-range year so they're neither boosted nor
# penalised for lacking one.
_RECENCY_WEIGHT_PER_YEAR = 0.0006
_NEUTRAL_YEAR = 2022


def _citation_year(citation: str) -> int:
    match = _YEAR_RE.search(citation)
    return int(match.group()) if match else _NEUTRAL_YEAR


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

    # Recency tie-breaker (from main): two rulings can be near-equally relevant to
    # a query (e.g. TR 2020/4 and TR 2025/2 both "about thin capitalisation"), and
    # with no supersession metadata to lean on, pure relevance ranking has no way
    # to prefer the newer one. Nudge the score toward whichever is more recent.
    for doc_id, doc in docs.items():
        scores[doc_id] += _citation_year(doc["citation"]) * _RECENCY_WEIGHT_PER_YEAR

    # Untruncated (Task C1): callers merge in other candidates (firm chunks, C4)
    # and re-rank the combined pool before truncating to top_k themselves.
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [
        {
            "id": doc_id,
            "citation": docs[doc_id]["citation"],
            "content": docs[doc_id]["content"],
            "source_url": docs[doc_id]["source_url"],
            "source_object_key": docs[doc_id].get("source_object_key"),
            "source_type": docs[doc_id].get("source_type"),
            "last_scraped_at": docs[doc_id].get("last_scraped_at"),
            "score": score,
        }
        for doc_id, score in ranked
    ]


async def _llm_rerank(query: str, candidates: list[dict], pool_scale: int = 1) -> list[dict]:
    """Re-order candidates with ONE batched Haiku relevance-scoring call (Task C1).

    Only invoked when RERANK_MODE == "llm". Sends the top RERANK_DEPTH candidates
    to a single cheap-model call that returns a relevance score per candidate; we
    re-order by that score and store it as `rerank_score`. A single structured LLM
    call over the whole batch — never one call per candidate. On any failure we
    fall back to the input order so retrieval never breaks over the re-rank.

    ``pool_scale`` (Task C3) multiplies the re-rank DEPTH for this ONE call so a
    reviewer-driven widened pass scores a proportionally wider batch, without
    mutating the global ``RERANK_DEPTH`` setting.
    """
    from taxflow.ports.llm import StructuredParseError
    from taxflow.services.agents.models import RerankScores

    depth = min(len(candidates), settings.RERANK_DEPTH * pool_scale)
    if depth == 0:
        return candidates
    batch = candidates[:depth]

    listing = "\n".join(
        f"[{i}] {c['citation']}: {c['content'][:500]}" for i, c in enumerate(batch)
    )
    system = (
        "You are a retrieval re-ranker for Australian tax law. Score how relevant "
        "each candidate passage is to the user's question from 0.0 (irrelevant) to "
        "1.0 (directly answers it). Return ONLY a JSON object with a `scores` field "
        "mapping the candidate index (as a string) to its score, "
        'e.g. {"scores": {"0": 0.9, "1": 0.2}}. No prose.'
    )
    user = f"Question: {query}\n\nCandidates:\n{listing}"

    try:
        result = await providers.get_llm().generate_structured(
            messages=[{"role": "user", "content": user}],
            system=system,
            model=providers.resolve_model("rerank"),
            output_model=RerankScores,
            max_tokens=500,
            temperature=0,
        )
        scores = {i: s for i, s in result.scores.items() if 0 <= i < depth}
    except StructuredParseError:
        # Structured validation failed: retry once as a plain generation and parse
        # tolerantly. Any failure here also falls back to the input order below.
        try:
            response = await providers.get_llm().generate(
                messages=[{"role": "user", "content": user}],
                system=system,
                model=providers.resolve_model("rerank"),
                max_tokens=500,
                temperature=0,
            )
            scores = _extract_scores((response.text or "").strip(), depth)
        except Exception:  # noqa: BLE001 - never fail retrieval over the re-rank
            return candidates
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
    # Accept BOTH the bare `{"0": 0.9}` map and the wrapped `{"scores": {...}}`
    # form (the structured RerankScores shape the fallback prompt now asks for).
    if isinstance(raw, dict) and isinstance(raw.get("scores"), dict):
        raw = raw["scores"]
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
    pool_scale: int = 1,
) -> list[dict]:
    """RRF candidate generation over a widened pool (Task C1). NEVER calls an LLM.

    Returns the merged RRF candidates (untruncated, unranked beyond RRF) so a
    caller can merge in other candidates (e.g. firm chunks, Task C4) and re-rank
    the combined pool together.

    ``pool_scale`` (Task C3) multiplies the effective candidate pool pulled from
    EACH of the semantic/text searches for this ONE call — a reviewer-driven
    widened pass passes ``pool_scale=2`` to look broader, WITHOUT mutating the
    global ``RERANK_CANDIDATE_POOL`` setting (so concurrent requests are never
    affected).
    """
    if embedding is None:
        embedding = await embed(query)

    text_query = normalise_query(query)
    pool = settings.RERANK_CANDIDATE_POOL * pool_scale
    store = providers.get_vector_store()
    semantic, textual = await asyncio.gather(
        store.semantic_search(embedding=embedding, source_types=source_types, limit=pool),
        store.text_search(query=text_query, source_types=source_types, limit=pool),
    )
    return _rrf_merge(semantic, textual)


async def generate_historical_candidates(
    query: str,
    embedding: list[float] | None = None,
    limit: int = 3,
) -> list[dict]:
    """Semantic-only candidate generation over SUPERSEDED chunks (Task B2).

    The historical/superseded pool is retrieved with a plain cosine search — NO
    RRF, text search, or re-rank — since these chunks are appended as a
    down-weighted historical pool below current law, never ranked against it.
    Reuses the caller-supplied embedding when provided (Task A4); embeds
    otherwise. Maps each row to a candidate dict carrying `score` (raw cosine
    similarity) and `superseded_by` (the supersession lineage).
    """
    if embedding is None:
        embedding = await embed(query)

    store = providers.get_vector_store()
    hits = await store.historical_search(embedding=embedding, limit=limit)
    return [
        {
            "id": str(h["id"]),
            "citation": h["citation"],
            "content": h["content"],
            "source_url": h.get("source_url"),
            "source_object_key": h.get("source_object_key"),
            "source_type": h.get("source_type"),
            "last_scraped_at": h.get("last_scraped_at"),
            "superseded_by": h.get("superseded_by"),
            "score": float(h["cosine_sim"]),
        }
        for h in hits
    ]


async def rerank_candidates(
    query: str, candidates: list[dict], pool_scale: int = 1
) -> list[dict]:
    """Apply RERANK_MODE to an already-merged candidate list (Task C1).

    "off"/"rrf_only" return the candidates unchanged (NO LLM call). "llm" runs a
    single batched Haiku relevance-scoring call and re-orders by score.
    ``pool_scale`` (Task C3) widens the re-rank depth for this one call only.
    """
    if settings.RERANK_MODE == "llm":
        return await _llm_rerank(query, candidates, pool_scale=pool_scale)
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
