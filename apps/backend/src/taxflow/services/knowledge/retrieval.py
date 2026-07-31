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


_DECOMPOSE_SYSTEM_PROMPT = """You are a search-query rewriter for an Australian tax law retrieval system.

Rewrite the question into a more specific, disambiguated search query that will match \
the RIGHT provision among near-identical SIBLING provisions - e.g. distinguish \
"concessional" from "non-concessional" contributions, or a specific numbered test from \
a general one, rather than leaving a term that could match either. Keep every specific \
term already in the question. Do NOT answer the question. Do NOT add prose, quotes, or \
explanation - return ONLY the rewritten search query text, 1-2 sentences."""


async def decompose_query(question: str) -> str:
    """Rewrite the question into a more specific search query via ONE cheap
    LLM call (RAG-quality audit precision follow-up #3), gated by
    QUERY_DECOMPOSITION_ENABLED (default off).

    Root cause this targets: retrieval repeatedly landed in the right
    Division but the wrong SIBLING Section (e.g. ITAA 1997 Subdivision 292-C
    "Excess non-concessional contributions tax" instead of 292-B's
    concessional cap) - the raw question's wording is sometimes genuinely
    ambiguous relative to how similarly-phrased sibling provisions are
    titled, closest to the LegalMALR pattern (multi-agent query
    understanding before statute retrieval). Scoped deliberately narrow:
    only rewrites the FULL-TEXT search leg (composed with normalise_query in
    generate_candidates), not the shared question embedding used across
    semantic/firm/historical search - full-text search is where an exact
    lexical distinction like "concessional" vs "non-concessional" actually
    helps, and this avoids re-plumbing the embedding that's computed once
    upstream and reused across several call sites. On any failure, returns
    the ORIGINAL question unchanged so retrieval never breaks over the
    rewrite - same never-fail contract as the LLM/Cohere rerankers.
    """
    if not settings.QUERY_DECOMPOSITION_ENABLED:
        return question
    try:
        response = await providers.get_llm().generate(
            messages=[{"role": "user", "content": question}],
            system=_DECOMPOSE_SYSTEM_PROMPT,
            model=providers.resolve_model("rerank"),
            max_tokens=150,
            temperature=0,
        )
        rewritten = (response.text or "").strip()
        return rewritten or question
    except Exception:  # noqa: BLE001 - never fail retrieval over the rewrite
        return question


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


# Hierarchical-chunking fields (Workstream C) copied onto every candidate dict.
# .get() so legacy NULL rows / flat mode flow through unchanged.
_HIERARCHY_FIELDS = ("heading_path", "parent_content", "chunk_level", "parent_key")


def _hierarchy_fields(src: dict) -> dict:
    return {field: src.get(field) for field in _HIERARCHY_FIELDS}


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
            "jurisdiction": docs[doc_id].get("jurisdiction"),
            **_hierarchy_fields(docs[doc_id]),
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

    # Jurisdiction is surfaced explicitly so the re-ranker can tell apart two
    # near-identically-titled rulings published independently by different
    # states (e.g. NSW vs WA "Commissioners Discretion To Exclude From A
    # Group") - without this the LLM has no signal that one is simply the
    # wrong state for the question asked, and a purely topical judgment can
    # rank the wrong-jurisdiction source first.
    listing = "\n".join(
        f"[{i}] {c['citation']} (jurisdiction: {c.get('jurisdiction') or 'federal'}): {c['content'][:500]}"
        for i, c in enumerate(batch)
    )
    system = (
        "You are a retrieval re-ranker for Australian tax law. Score how relevant "
        "each candidate passage is to the user's question from 0.0 (irrelevant) to "
        "1.0 (directly answers it). If the question names a specific state/territory, "
        "a candidate from a DIFFERENT jurisdiction is almost never a correct answer even "
        "if its title looks similar - score it low. Return ONLY a JSON object with a "
        "`scores` field mapping the candidate index (as a string) to its score, "
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


async def _cohere_rerank(query: str, candidates: list[dict], pool_scale: int = 1) -> list[dict]:
    """Re-order candidates with ONE Cohere Rerank call via OpenRouter's hosted
    /rerank endpoint (Task: RAG-quality audit precision follow-up).

    Only invoked when RERANK_MODE == "cohere". A cross-encoder does fine-
    grained joint query/passage scoring, which is specifically better than
    RRF (a bag-of-words-ish fusion score) or the LLM reranker's coarse 0-1
    judgment at discriminating between structurally-similar sibling
    provisions (e.g. ITAA 1997 Subdivision 292-B vs 292-C) - the exact
    "right Division, wrong Section" failure pattern the audit found. Hosted
    via OpenRouter rather than a local cross-encoder model, since this
    backend deliberately carries no ML/torch dependency (see RERANK_MODE's
    docstring - 2 vCPU / 4GB droplet). On any failure we fall back to the
    input order so retrieval never breaks over the re-rank, same contract
    as ``_llm_rerank``.
    """
    import httpx

    depth = min(len(candidates), settings.RERANK_DEPTH * pool_scale)
    if depth == 0 or not settings.OPENROUTER_API_KEY:
        return candidates
    batch = candidates[:depth]
    documents = [
        f"{c['citation']} (jurisdiction: {c.get('jurisdiction') or 'federal'}): {c['content']}"
        for c in batch
    ]

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/rerank",
                headers={"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"},
                json={
                    "model": settings.RERANK_OPENROUTER_MODEL,
                    "query": query,
                    "documents": documents,
                },
            )
            resp.raise_for_status()
            results = resp.json()["results"]
    except Exception:  # noqa: BLE001 - never fail retrieval over the re-rank
        return candidates

    for r in results:
        idx = r.get("index")
        if idx is not None and 0 <= idx < len(batch):
            batch[idx]["rerank_score"] = r.get("relevance_score", 0.0)
    reranked = sorted(batch, key=lambda c: c.get("rerank_score", 0.0), reverse=True)
    # Candidates beyond the re-rank depth keep their RRF order, appended after.
    return reranked + candidates[depth:]


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


def apply_jurisdiction_boost(candidates: list[dict], jurisdiction_hint: str | None) -> list[dict]:
    """SOFT BOOST candidates whose `jurisdiction` matches an explicitly-named
    AU state/territory in the question. Never excludes anything.

    Root-caused via the RAG-quality experiment: a question naming "New South
    Wales" retrieved a Western Australia ruling instead, because nothing in
    retrieval was jurisdiction-aware - state revenue offices publish near-
    identically-titled rulings ("Commissioners Discretion To Exclude From A
    Group") independently per state, and neither RRF's text/semantic score nor
    the LLM re-ranker's prompt carried jurisdiction, so a topically-similar
    ruling from the WRONG state could out-rank the right one. Mirrors
    ``apply_source_type_boost``'s soft-boost-only design: a document from a
    different jurisdiction keeps its score and stays retrievable (e.g. a
    federal ITAA provision must never be excluded just because a state was
    named elsewhere in the question).
    """
    if not jurisdiction_hint or settings.JURISDICTION_BOOST_WEIGHT <= 0:
        return candidates
    multiplier = 1.0 + settings.JURISDICTION_BOOST_WEIGHT
    for cand in candidates:
        if cand.get("jurisdiction") == jurisdiction_hint:
            cand["score"] = cand.get("score", 0.0) * multiplier
    return sorted(candidates, key=lambda c: c.get("score", 0.0), reverse=True)


_LEAF_TITLE_RE = re.compile(r"\(([^()]+)\)\s*$")
_TITLE_BOOST_STOPWORDS = {
    "a", "an", "the", "of", "for", "and", "or", "to", "in", "on", "is", "are",
    "what", "how", "does", "do", "when", "can", "this", "that", "with", "by",
    "be", "was", "were", "as", "at", "from", "it", "its",
}


def _content_tokens(text: str) -> set[str]:
    return {
        w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
        if w not in _TITLE_BOOST_STOPWORDS and len(w) > 2
    }


def _leaf_title(heading_path: str | None) -> str | None:
    """The parenthetical description of a heading_path's LAST breadcrumb
    segment, e.g. "...> Section 292-105 (CGT cap amount)" -> "CGT cap amount".
    """
    if not heading_path:
        return None
    last_segment = heading_path.split(">")[-1]
    m = _LEAF_TITLE_RE.search(last_segment.strip())
    return m.group(1) if m else None


def apply_section_title_boost(candidates: list[dict], question: str) -> list[dict]:
    """SOFT BOOST candidates whose own section/heading title shares content
    words with the question (RAG-quality audit precision follow-up #2).

    Root cause: retrieval repeatedly landed in the right Division but the
    WRONG sibling Section (e.g. ITAA 1997 Subdivision 292-C "Excess non-
    concessional contributions tax" instead of 292-B's concessional cap, for
    a question about the CONCESSIONAL contributions cap) - RRF's score is a
    fusion of whole-chunk relevance and doesn't specifically weigh whether
    the section's OWN title matches the question's specific terms. This is
    a cheap, deterministic, no-LLM/no-API complement to the Cohere
    cross-encoder rerank (RERANK_MODE="cohere") - useful even when that mode
    is off, since it runs at the RRF-merge stage before any rerank.

    Non-legislation candidates (no heading_path/section title, e.g. rulings)
    are simply never boosted - never penalised either, since the boost only
    ever multiplies a matching candidate's score upward.
    """
    if settings.SECTION_TITLE_BOOST_WEIGHT <= 0:
        return candidates
    q_tokens = _content_tokens(question)
    if not q_tokens:
        return candidates
    for cand in candidates:
        title = _leaf_title(cand.get("heading_path"))
        if not title:
            continue
        title_tokens = _content_tokens(title)
        if not title_tokens:
            continue
        overlap = len(q_tokens & title_tokens) / len(title_tokens)
        if overlap > 0:
            cand["score"] = cand.get("score", 0.0) * (
                1.0 + settings.SECTION_TITLE_BOOST_WEIGHT * overlap
            )
    return sorted(candidates, key=lambda c: c.get("score", 0.0), reverse=True)


def cap_per_source_url(candidates: list[dict], max_per_url: int) -> list[dict]:
    """Cap how many candidates from the SAME source_url can occupy the pool,
    preserving overall rank order otherwise.

    Root-caused via the RAG-quality experiment: a single long ruling chunked
    with overlapping windows can place 13+ near-duplicate chunks at the top of
    the candidate pool (e.g. TR 2024/4 for a SMSF contribution-cap question),
    crowding out a different, more precisely on-point source (ITAA 1997
    s.292-25) that would otherwise have made the pool. This doesn't drop the
    dominant document - it still keeps its best ``max_per_url`` chunks - it
    just stops one document from monopolizing the whole pool. No-op when
    ``max_per_url`` is falsy (0/None disables the cap).
    """
    if not max_per_url:
        return candidates
    counts: dict[str, int] = {}
    capped = []
    for cand in candidates:
        url = cand.get("source_url") or ""
        counts[url] = counts.get(url, 0) + 1
        if counts[url] <= max_per_url:
            capped.append(cand)
    return capped


async def generate_candidates(
    query: str,
    source_types: list[str] | None = None,
    embedding: list[float] | None = None,
    pool_scale: int = 1,
) -> list[dict]:
    """RRF candidate generation over a widened pool (Task C1).

    Returns the merged RRF candidates (untruncated, unranked beyond RRF) so a
    caller can merge in other candidates (e.g. firm chunks, Task C4) and re-rank
    the combined pool together.

    ``pool_scale`` (Task C3) multiplies the effective candidate pool pulled from
    EACH of the semantic/text searches for this ONE call — a reviewer-driven
    widened pass passes ``pool_scale=2`` to look broader, WITHOUT mutating the
    global ``RERANK_CANDIDATE_POOL`` setting (so concurrent requests are never
    affected).

    Calls an LLM ONLY when QUERY_DECOMPOSITION_ENABLED is on (default off) -
    see ``decompose_query``'s docstring. That rewrite affects the full-text
    search leg only; the embedding (passed in or computed here from the
    ORIGINAL query) is untouched, since it's shared/reused across several
    call sites upstream.
    """
    if embedding is None:
        embedding = await embed(query)

    text_query = normalise_query(await decompose_query(query))
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
            **_hierarchy_fields(h),
            "score": float(h["cosine_sim"]),
        }
        for h in hits
    ]


async def rerank_candidates(
    query: str, candidates: list[dict], pool_scale: int = 1
) -> list[dict]:
    """Apply RERANK_MODE to an already-merged candidate list (Task C1).

    "off"/"rrf_only" return the candidates unchanged (NO LLM call). "llm" runs a
    single batched Haiku relevance-scoring call and re-orders by score. "cohere"
    runs one Cohere Rerank API call (a cross-encoder, not an LLM) - see
    ``_cohere_rerank`` for why this exists. ``pool_scale`` (Task C3) widens the
    re-rank depth for this one call only.
    """
    if settings.RERANK_MODE == "llm":
        return await _llm_rerank(query, candidates, pool_scale=pool_scale)
    if settings.RERANK_MODE == "cohere":
        return await _cohere_rerank(query, candidates, pool_scale=pool_scale)
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
