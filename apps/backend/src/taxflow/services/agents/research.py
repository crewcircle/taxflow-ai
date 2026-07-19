import logging
import re
import time

from taxflow import providers
from taxflow.config import settings
from taxflow.services.prompt_cache import cacheable_system
from taxflow.services.knowledge.retrieval import (
    apply_source_type_boost,
    generate_candidates,
    generate_historical_candidates,
    rerank_candidates,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are TaxFlow AI, an AI assistant for Australian public practice accounting firms.
You answer questions about Australian tax law with precision and citations.

Rules:
1. Base your answer ONLY on the provided source documents. Do not use training knowledge.
2. Every factual claim must cite a specific source using [N] notation matching the context.
3. Use Australian English spelling (organisation, licence, recognise, cheque, lodgement).
4. Never give generic advice. Be specific to Australian law and ATO positions.
5. If the provided context does not contain enough information, say:
   "The provided sources do not contain sufficient information to answer this question
   with confidence. Consider consulting the full text of [specific source] or requesting
   a Private Binding Ruling from the ATO."
6. Format: 2-4 paragraphs. First paragraph: direct answer. Subsequent: analysis and
   nuance. Final: practical implications or recommended action.
7. If the facts involve cross-border dealings, related parties, or debt/financing
   structures, explicitly check whether other regimes interact with the primary
   question - transfer pricing (Division 815), hybrid mismatch rules (Division 832),
   or debt deduction creation rules (s820-423) commonly apply alongside thin
   capitalisation and are easy to miss if only the literal question is answered.
   Only raise a regime if the provided sources actually support it - do not
   speculate about interactions the sources don't cover.
8. A source labelled [HISTORICAL — ...] is a SUPERSEDED position and is NOT
   current law. Use it ONLY to explain how a position changed over time (what
   the rule USED to be); never cite it as the current authority for what the
   law is now. The current answer must rest on the non-historical sources.
9. End with a "Sources" section listing all cited documents.
"""

CONTEXT_TOKEN_LIMIT = 60_000
CITATION_PATTERN = re.compile(r"\[(\d+)\]")


def _system_blocks() -> list[dict] | str:
    """The research system prompt as a cacheable content block (Task B1).

    The prompt is large and fully static, so it forms a stable cacheable prefix;
    marking it ephemeral lets repeat calls (Haiku + Sonnet, back-to-back queries
    within the 5-min TTL) read it from cache at ~10% of the input price.
    """
    return cacheable_system(SYSTEM_PROMPT)


def route_model(signals: dict) -> str:
    """Pick "haiku" or "sonnet" BEFORE the single generation call (Task A3).

    Uses only retrieval signals available WITHOUT any LLM call, so we never pay
    for a throwaway generation just to decide the model:
      - num_chunks:  how many chunks retrieval returned.
      - top_score:   the top RRF score (or re-rank score once C1 lands) over the
                     global candidate pool.
      - insufficient: True when hybrid search returned nothing (the "insufficient
                     information" retrieval situation).
      - rerank_top_score: optional; from C1's LLM re-ranker when present. This is
                     a 0-1 relevance score on a DIFFERENT scale from the RRF
                     top_score, so it is compared against its own threshold
                     (ROUTE_MIN_RERANK_SCORE) — NOT the RRF threshold. A weak
                     rerank score must not sneak past the (much smaller) RRF
                     threshold and route a weak result to Haiku.

    Strong, confident retrieval -> Haiku is enough. Anything weak or ambiguous
    routes to Sonnet: we deliberately bias toward Sonnet so a mis-tuned router
    never silently sends a hard question to the weaker model.
    """
    if signals.get("insufficient") or signals.get("num_chunks", 0) == 0:
        return "sonnet"

    num_chunks = signals.get("num_chunks", 0)
    top_score = signals.get("top_score", 0.0) or 0.0
    rerank_top = signals.get("rerank_top_score")

    # Retrieval is "strong" when the RRF top score clears the RRF threshold OR
    # (when an LLM rerank score is present) that rerank score clears its own
    # 0-1-scale threshold. Each score is judged on its own scale.
    score_strong = top_score >= settings.ROUTE_MIN_TOP_RRF_SCORE
    if rerank_top is not None:
        score_strong = score_strong or rerank_top >= settings.ROUTE_MIN_RERANK_SCORE

    strong = num_chunks >= settings.ROUTE_MIN_STRONG_CHUNKS and score_strong
    return "haiku" if strong else "sonnet"


def build_client_profile(client: dict | None) -> str:
    """Build a compact ADVISORY client-profile steering string (Task D1).

    Uses fields already on the `clients` row fetched by auth (business_type,
    state, firm_style jsonb) — no extra query. The result is injected into the
    research + drafter prompts as advisory steering ("weight jurisdiction/
    industry-specific guidance accordingly"), NOT a hard filter, so it can never
    starve a correct general-law answer. Returns "" when disabled or when there's
    nothing useful to say, in which case prompts behave exactly as before.
    """
    if not settings.PROFILE_INJECTION_ENABLED or not client:
        return ""

    business_type = client.get("business_type")
    state = client.get("state")

    bits: list[str] = []
    if business_type and state:
        bits.append(f"The firm is a {business_type} practice in {state}")
    elif business_type:
        bits.append(f"The firm is a {business_type} practice")
    elif state:
        bits.append(f"The firm is based in {state}")

    # firm_style jsonb: surface a few short highlights if present (e.g. tone,
    # specialties). Values are kept short so they steer without dominating.
    firm_style = client.get("firm_style")
    if isinstance(firm_style, dict) and firm_style:
        highlights = []
        for key, value in firm_style.items():
            if isinstance(value, (str, int, float, bool)):
                highlights.append(f"{key}: {value}")
            if len(highlights) >= 3:
                break
        if highlights:
            bits.append("firm style — " + "; ".join(highlights))

    if not bits:
        return ""

    return (
        "Client profile (advisory only — weight jurisdiction/industry-specific "
        "guidance accordingly, but never withhold correct general Australian law): "
        + ". ".join(bits)
        + "."
    )


# source_type enum (003_knowledge_chunks.sql):
#   ato_ruling, ato_determination, ato_pbr, legislation, court_decision,
#   ato_guide, ato_news.
_MODULE_SOURCE_TYPES = {
    # A firm module hints at the kinds of authority most relevant to it. These
    # are SOFT boosts only (Task D2), never exclusions.
    "research": ["legislation", "ato_ruling"],
    "ato_correspondence": ["ato_ruling", "ato_determination", "ato_pbr"],
    "regulatory_monitor": ["ato_news", "ato_guide"],
}
_INTENT_SOURCE_TYPES = [
    (re.compile(r"\b(legislation|act|section|s\d|itaa|statut)", re.IGNORECASE), ["legislation"]),
    (re.compile(r"\b(ruling|tr \d|td \d|determination)", re.IGNORECASE),
     ["ato_ruling", "ato_determination"]),
    (re.compile(r"\b(private binding ruling|pbr)", re.IGNORECASE), ["ato_pbr"]),
    (re.compile(r"\b(court|tribunal|aat|federal court|decision|case law)", re.IGNORECASE),
     ["court_decision"]),
]


def derive_source_type_hint(question: str, active_modules: list[str] | None) -> list[str] | None:
    """Derive a source_types SOFT-BOOST hint (Task D2) from question intent and
    the firm's active_modules. Returns None when nothing matches (no boost).

    This is ONLY a hint: retrieval widens the pool unfiltered and boosts matching
    source_types during scoring, so nothing is excluded outright (see
    SOURCE_TYPE_FILTER_MODE for the opt-in hard filter).
    """
    hints: list[str] = []
    for pattern, types in _INTENT_SOURCE_TYPES:
        if pattern.search(question or ""):
            hints.extend(types)
    for module in active_modules or []:
        hints.extend(_MODULE_SOURCE_TYPES.get(module, []))
    # De-dup preserving order.
    seen: set[str] = set()
    deduped = [t for t in hints if not (t in seen or seen.add(t))]
    return deduped or None


def build_session_block(history: list[dict]) -> str:
    """Build a compact "conversation so far" block (Task D3).

    history is a list of prior turns {question, answer} for the SAME
    (client_id, session_id), oldest first. Each prior answer is SUMMARISED AT
    READ TIME (truncated to SESSION_SUMMARY_CHARS) to protect the token budget —
    we deliberately do not store summaries. Returns "" for empty history so
    single-shot queries are unaffected.
    """
    if not history:
        return ""
    header = "Conversation so far (prior turns in this session, for context only):"
    lines = [header]
    total = len(header)
    for turn in history:
        q = (turn.get("question") or "").strip()
        a = (turn.get("answer") or "").strip()
        if len(q) > settings.SESSION_QUESTION_CHARS:
            q = q[: settings.SESSION_QUESTION_CHARS] + "…"
        summary = a[: settings.SESSION_SUMMARY_CHARS]
        if len(a) > settings.SESSION_SUMMARY_CHARS:
            summary += "…"
        line = f"- Q: {q}\n  A: {summary}"
        # Total-block budget: stop adding turns once we'd exceed the cap so a
        # long session can't blow up prompt size/cost despite SESSION_HISTORY_N.
        if total + len(line) + 1 > settings.SESSION_BLOCK_MAX_CHARS:
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines)


def _compute_knowledge_as_of(chunks: list[dict], citations: list[dict]) -> str | None:
    """Freshness stamp for the answer (Task B3): the newest ``last_scraped_at``
    over the CITED, current (non-historical) source chunks, formatted
    ``YYYY-MM-DD``.

    Historical/superseded chunks are ignored (they describe past law, not the
    current knowledge date) and firm-knowledge chunks carry
    ``last_scraped_at=None`` (no scrape concept), so they never contribute.
    Returns None when no cited current chunk has a scrape date — the trace then
    renders no freshness stamp.
    """
    cited = {c["citation"] for c in citations}
    dates = []
    for chunk in chunks:
        if chunk.get("is_historical"):
            continue
        if chunk.get("citation") not in cited:
            continue
        last_scraped_at = chunk.get("last_scraped_at")
        if last_scraped_at is None:
            continue
        dates.append(last_scraped_at)
    if not dates:
        return None
    return max(dates).strftime("%Y-%m-%d")


def _firm_profile_summary(client: dict) -> str | None:
    """A short, business-readable summary of the firm profile applied to the
    answer (Task C6) — surfaced on ``trace.firm.profile_summary`` so the "why
    this answer?" UI can say, in one line, how the firm's profile steered the
    result. Built from the same ``clients`` fields ``build_client_profile`` uses
    (business_type, state, firm_style). Returns None when there's nothing to say.
    """
    parts: list[str] = []
    business_type = client.get("business_type")
    state = client.get("state")
    if business_type and state:
        parts.append(f"{business_type} practice in {state}")
    elif business_type:
        parts.append(f"{business_type} practice")
    elif state:
        parts.append(f"based in {state}")

    firm_style = client.get("firm_style")
    if isinstance(firm_style, dict) and firm_style:
        keys = list(firm_style.keys())[:3]
        parts.append("firm style: " + ", ".join(str(k) for k in keys))

    return ". ".join(parts) or None


def build_firm_profile_fragment(client: dict | None) -> dict:
    """The C-owned ``trace.firm`` fragment (Task C6): whether the firm profile
    and voice steering were applied, plus a short human-readable summary.

    ``profile_applied`` mirrors whether ``build_client_profile`` produced any
    advisory profile block (so it also respects PROFILE_INJECTION_ENABLED);
    ``voice_applied`` is true when the client carries a non-empty ``firm_style``
    jsonb (the firm-voice highlights folded into the profile block). Returns an
    EMPTY dict when neither applies (or there is no client), so ``trace.firm``
    stays absent unless there is real firm content — this fragment is MERGED
    with B's ``firm_items``/``firm_items_used`` fragment (disjoint keys) before
    ``_build_trace``, so neither side overwrites the other (co-ownership).
    ``usage_trend`` is added by the caller (it needs an async repo read).
    """
    if not client:
        return {}
    profile_applied = bool(build_client_profile(client))
    firm_style = client.get("firm_style")
    voice_applied = isinstance(firm_style, dict) and bool(firm_style)
    if not (profile_applied or voice_applied):
        return {}
    return {
        "profile_applied": profile_applied,
        "voice_applied": voice_applied,
        "profile_summary": _firm_profile_summary(client),
    }


def build_session_fragment(
    prior_turns_used: int,
    engagement_memos_used: int,
    client_ref: str | None,
) -> dict | None:
    """The C-owned ``trace.session`` fragment (Task C6): how much conversational
    and engagement context steered this answer.

    ``prior_turns_used`` is the number of prior turns in this session loaded into
    the "conversation so far" block; ``engagement_memos_used`` is the number of
    engagement-context memos merged into retrieval (Task C4); ``client_ref`` is
    the engagement reference from the request. Returns None when there is no
    session/engagement context at all, so ``trace.session`` stays absent for a
    plain single-shot query.
    """
    if not (prior_turns_used or engagement_memos_used or client_ref):
        return None
    return {
        "prior_turns_used": prior_turns_used,
        "engagement_memos_used": engagement_memos_used,
        "client_ref": client_ref,
    }


def build_firm_items(chunks: list[dict], citations: list[dict]) -> dict:
    """The B-owned ``trace.firm`` fragment (Task B3): the firm-knowledge chunks
    that were in the retrieved pool, each flagged with whether it was actually
    cited in the answer.

    Firm chunks are identified by their citation starting with
    ``"Firm knowledge:"`` (the convention firm_search emits). Returns
    ``{firm_items: [{citation, cited_in_answer}], firm_items_used: int}`` where
    ``firm_items_used`` counts the cited firm items. This is MERGED with C's
    ``trace.firm`` fragment (profile/voice/usage_trend) before ``_build_trace``.
    """
    cited = {c["citation"] for c in citations}
    firm_items = [
        {
            "citation": chunk["citation"],
            "cited_in_answer": chunk["citation"] in cited,
        }
        for chunk in chunks
        if chunk.get("citation", "").startswith("Firm knowledge:")
    ]
    return {
        "firm_items": firm_items,
        "firm_items_used": sum(1 for item in firm_items if item["cited_in_answer"]),
    }


class ResearchAgent:
    def __init__(self, llm=None) -> None:
        # LLMPort injected (Task A5); defaults to the configured provider so
        # existing callers (routers, tests) construct it with no arguments.
        self._llm = llm if llm is not None else providers.get_llm()

    async def _retrieve_context(
        self,
        question: str,
        client_id: str,
        embedding: list[float] | None = None,
        source_type_hint: list[str] | None = None,
        pool_scale: int = 1,
        client_ref: str | None = None,
    ) -> tuple[list[dict], dict]:
        """Retrieve merged global + firm chunks and the routing signals.

        The single query embedding is passed down so both the global hybrid search
        and the firm-knowledge search reuse it (Task A4) instead of each paying a
        separate OpenAI round trip.

        Task C4: global and firm candidates are merged into ONE pool and ranked
        together (honouring FIRM_CHUNK_WEIGHT) rather than truncating global to
        top_k and blindly appending firm chunks after. If C1's re-rank is active
        it runs over the combined pool, so firm chunks compete on the same
        relevance scale as global chunks. Final truncation is to RETRIEVAL_TOP_K.

        Task D2: source_type_hint is applied as a SOFT BOOST by default — the pool
        is retrieved UNFILTERED (so a non-matching source is still retrievable) and
        matching source_types are boosted during scoring. Only when
        SOURCE_TYPE_FILTER_MODE == "hard" is the hint passed as a hard SQL filter.

        Task C3: ``pool_scale`` multiplies the effective candidate/global/firm
        pool sizes for THIS ONE call only. A reviewer-driven widened corrective
        pass (see ``regenerate_with_feedback(widen=True)`` / ``graph.re_retrieve``)
        passes ``pool_scale=2`` to look at a broader pool, threaded as a parameter
        so the global ``settings`` pool sizes are NEVER mutated and concurrent
        requests can never inherit a widened pool.

        Returns (chunks, signals). Routing signals (Task A3) are derived from the
        GLOBAL candidate pool only: firm chunks carry a weighted score on a
        different scale, so mixing them in would distort the RRF-based thresholds.
        """
        # Only a hard-mode hint reaches the SQL filter; soft mode retrieves the
        # full pool and boosts after (never excludes the one relevant doc).
        sql_source_types = (
            source_type_hint if settings.SOURCE_TYPE_FILTER_MODE == "hard" else None
        )
        global_candidates = await generate_candidates(
            question,
            source_types=sql_source_types,
            embedding=embedding,
            pool_scale=pool_scale,
        )
        if settings.SOURCE_TYPE_FILTER_MODE != "hard":
            global_candidates = apply_source_type_boost(global_candidates, source_type_hint)
        firm_candidates = await self._firm_knowledge_search(
            question,
            client_id,
            top_k=settings.RETRIEVAL_FIRM_POOL * pool_scale,
            embedding=embedding,
        )

        # Engagement context (Task C4): prior client-facing memos saved for THIS
        # engagement (client_ref) are advisory context specific to this client.
        # Retrieved only when enabled + a client_ref is present, weighted by
        # ENGAGEMENT_CHUNK_WEIGHT, and merged into the same pool BEFORE rerank so
        # they compete on the same relevance scale as global + firm chunks.
        engagement_candidates: list[dict] = []
        if settings.ENGAGEMENT_CONTEXT_ENABLED and client_ref:
            engagement_candidates = await self._engagement_search(
                question,
                client_id,
                client_ref,
                top_k=settings.RETRIEVAL_ENGAGEMENT_POOL * pool_scale,
                embedding=embedding,
            )

        # Routing signals from the GLOBAL pool only (before merging in firm docs).
        signals = {
            "num_chunks": len(global_candidates),
            "top_score": max((c["score"] for c in global_candidates), default=0.0),
            "insufficient": len(global_candidates) == 0,
        }

        # Merge into one pool. Firm chunks already carry score = sim * FIRM_CHUNK_WEIGHT
        # (see _firm_knowledge_search), so they participate in the ranking instead
        # of being appended after global truncation. The global slice is widened by
        # pool_scale for this call only (never via the global settings value).
        merged = (
            global_candidates[: settings.RETRIEVAL_GLOBAL_POOL * pool_scale]
            + firm_candidates
            + engagement_candidates
        )
        merged.sort(key=lambda c: c.get("score", 0.0), reverse=True)

        # If C1's re-rank is active, run the combined pool (global + firm) through
        # the same re-ranker so firm chunks are judged on relevance too.
        reranked = await rerank_candidates(question, merged, pool_scale=pool_scale)

        chunks = reranked[: settings.RETRIEVAL_TOP_K]

        # Surface the re-rank top score to the router (Task A3 accepts it) so a
        # strong LLM-judged relevance can promote to Haiku.
        rerank_scores = [c["rerank_score"] for c in chunks if "rerank_score" in c]
        if rerank_scores:
            signals["rerank_top_score"] = max(rerank_scores)

        # Historical / superseded pool (Task B2): appended AFTER truncation to the
        # authoritative top-K so it never displaces current law, and excluded from
        # `signals` (routing is derived from the current-law global pool only). Each
        # historical chunk is down-weighted (SUPERSEDED_CHUNK_WEIGHT < 1.0) and
        # tagged so the trace/UI can render it as a superseded historical reference.
        # Wrapped in the same narrow DB/connection failure guard as the firm
        # search: a failure here must never fail the query.
        if settings.SUPERSEDED_RETRIEVAL_ENABLED:
            import psycopg2

            try:
                historical = await generate_historical_candidates(
                    question,
                    embedding=embedding,
                    limit=settings.SUPERSEDED_POOL_SIZE,
                )
            except (psycopg2.Error, OSError) as e:
                logger.warning("historical retrieval search failed: %s", e)
                historical = []

            for hist in historical:
                hist["score"] = hist.get("score", 0.0) * settings.SUPERSEDED_CHUNK_WEIGHT
                hist["is_historical"] = True
                hist["is_superseded"] = True
            historical.sort(key=lambda c: c.get("score", 0.0), reverse=True)
            historical = historical[: settings.SUPERSEDED_POOL_SIZE]
            chunks = chunks + historical

        return chunks, signals

    async def _firm_knowledge_search(
        self, question: str, client_id: str, top_k: int, embedding: list[float] | None = None
    ) -> list[dict]:
        import psycopg2

        from taxflow.services.knowledge.embedder import embed

        # Reuse the single query embedding when the caller passed it (Task A4);
        # only embed here if invoked standalone.
        query_embedding = embedding if embedding is not None else await embed(question)

        try:
            hits = await providers.get_vector_store().firm_search(
                embedding=query_embedding, client_id=client_id, limit=top_k
            )
        except (psycopg2.Error, OSError) as e:
            # Firm knowledge is optional and must never fail the query. But
            # swallowing every error silently (the old `except Exception: return
            # []`) meant missing firm context was invisible. Narrow to the
            # expected DB / connection failures and LOG them so a persistent
            # problem (bad pool, missing table, embedding issue) is observable,
            # while still returning [] so the query proceeds on global sources.
            logger.warning(
                "firm knowledge search failed for client_id=%s: %s", client_id, e
            )
            return []

        # FIRM_CHUNK_WEIGHT (Task C4): firm documents are more specific to the
        # client than global sources, so we weight their similarity score. Unlike
        # the old dead 1.5x, this score now participates in the merged ranking in
        # _retrieve_context instead of being appended after global truncation.
        for hit in hits:
            hit["score"] = float(hit["score"]) * settings.FIRM_CHUNK_WEIGHT
        return hits

    async def _engagement_search(
        self,
        question: str,
        client_id: str,
        client_ref: str,
        top_k: int,
        embedding: list[float] | None = None,
    ) -> list[dict]:
        """Retrieve prior engagement memos for THIS client engagement (Task C4).

        Mirrors :meth:`_firm_knowledge_search`: reuses the single query embedding
        when passed, wraps the vector-store call in the same narrow
        ``(psycopg2.Error, OSError)`` guard so a failure logs + returns [] rather
        than failing the query, and applies ENGAGEMENT_CHUNK_WEIGHT in the service
        layer (the adapter carries the raw similarity as ``score``).
        """
        import psycopg2

        from taxflow.services.knowledge.embedder import embed

        query_embedding = embedding if embedding is not None else await embed(question)

        try:
            hits = await providers.get_vector_store().engagement_search(
                embedding=query_embedding,
                client_id=client_id,
                client_ref=client_ref,
                limit=top_k,
            )
        except (psycopg2.Error, OSError) as e:
            logger.warning(
                "engagement context search failed for client_id=%s client_ref=%s: %s",
                client_id,
                client_ref,
                e,
            )
            return []

        # ENGAGEMENT_CHUNK_WEIGHT (Task C4): a prior engagement memo is highly
        # specific to this client engagement, so its similarity is weighted so it
        # participates in the merged ranking above equivalent global sources.
        for hit in hits:
            hit["score"] = float(hit["score"]) * settings.ENGAGEMENT_CHUNK_WEIGHT
        return hits

    def _build_context_string(self, chunks: list[dict]) -> str:
        parts = []
        for i, chunk in enumerate(chunks, start=1):
            # Historical / superseded sources (Task B3): prefix a loud label so
            # the model treats them as "how the position changed", never as
            # current law. Authoritative chunks render exactly as before.
            prefix = ""
            if chunk.get("is_historical"):
                superseded_by = chunk.get("superseded_by")
                if superseded_by:
                    prefix = (
                        f"[HISTORICAL — superseded by {superseded_by}, "
                        "do not treat as current law] "
                    )
                else:
                    prefix = (
                        "[HISTORICAL — superseded, do not treat as current law] "
                    )
            parts.append(
                f"[{i}] {prefix}Citation: {chunk['citation']}\n"
                f"Source: {chunk['source_url']}\n"
                f"Content: {chunk['content']}\n---"
            )
        context = "\n".join(parts)
        # Rough token truncation (4 chars ~= 1 token)
        max_chars = CONTEXT_TOKEN_LIMIT * 4
        return context[:max_chars]

    def _user_content(self, question: str, context: str, steering: str = "") -> str:
        """Assemble the user message.

        `steering` carries the ADVISORY client-profile block (Task D1) and the
        "conversation so far" session block (Task D3). It is prepended before the
        question/sources so it steers without being mistaken for a source
        document. Empty steering reproduces the original prompt exactly, so
        single-shot / no-profile queries are unchanged.
        """
        prefix = f"{steering}\n\n" if steering else ""
        return f"{prefix}Question: {question}\n\nSource documents:\n{context}"

    async def _generate(
        self, question: str, context: str, model: str, steering: str = ""
    ) -> tuple[str, dict]:
        result = await self._llm.generate(
            messages=[{"role": "user", "content": self._user_content(question, context, steering)}],
            system=_system_blocks(),
            model=model,
            max_tokens=1500,
            temperature=0,
        )
        answer = result.text
        usage = result.usage
        # Capture prompt-cache token usage (Task B1) alongside the existing token
        # reads. The port's Usage record already normalises the four counters.
        return answer, usage.as_dict()

    def _estimate_confidence(self, answer: str, chunks: list[dict], citations: list[dict]) -> float:
        """Deterministic confidence from retrieval/citation signals. Replaces the LLM
        self-grading call, which was badly miscalibrated (0.05 on correct answers) and
        escalated 26/30 accuracy questions to Sonnet for no accuracy gain.

        Kept for reporting + verify-gating (Task A3 decouples it from model choice; the
        model is now routed pre-generation from retrieval signals)."""
        if "do not contain sufficient information" in answer.lower():
            return 0.30
        confidence = 0.35
        confidence += min(len(citations), 4) * 0.10  # cited sources, up to +0.40
        confidence += min(len(chunks), 8) * 0.02  # retrieval depth, up to +0.16
        return round(min(confidence, 0.95), 2)

    def _trim_excerpt(self, content: str, max_len: int = 200) -> str:
        """Trim to a sentence or word boundary instead of a hard character
        cut, so the excerpt reads as an actual quoted passage - this is what
        the UI shows as "the relevant section" of a source, and what a
        deep-link's browser-side text search matches against."""
        if len(content) <= max_len:
            return content
        window = content[: max_len + 40]
        sentence_end = max(window.rfind(". "), window.rfind("? "), window.rfind("! "))
        if sentence_end > max_len * 0.5:
            return window[: sentence_end + 1]
        space = content.rfind(" ", 0, max_len)
        cutoff = space if space > 0 else max_len
        return content[:cutoff].rstrip(",;: ") + "…"

    def _build_trace(
        self,
        chunks: list[dict],
        citations: list[dict],
        source_type_hint: list[str] | None,
        routed: str,
        stats: dict,
        confidence: float,
        firm: dict | None = None,
        session: dict | None = None,
        knowledge_as_of: str | None = None,
        firm_knowledge_used: list[str] | None = None,
    ) -> dict:
        """Answer-flow transparency: capture what retrieval actually returned and
        what generation actually did, so a "why this answer?" UI can show it
        without re-deriving it. Additive only - every existing caller/field is
        unaffected by this.

        Workstream A owns the SHAPE and the null defaults of every field, even
        those the B/C workstreams thread real values into later; passing the
        defaults (firm/session None, knowledge_as_of None, chunks without the new
        lifecycle keys) keeps the emitted trace byte-identical to the pre-A1
        output. ``firm``/``session`` are emitted ONLY when the (already-merged)
        input dict is non-empty, so an absent block never appears as an empty
        object.
        """
        cited = {c["citation"] for c in citations}
        candidates = [
            {
                "n": i + 1,
                "citation": chunk["citation"],
                "source_type": chunk.get("source_type"),
                "is_firm_knowledge": chunk["citation"].startswith("Firm knowledge:"),
                "score": round(chunk.get("score", 0.0), 4),
                "cited_in_answer": chunk["citation"] in cited,
                # Knowledge-lifecycle flags (populated by workstream B; null-safe
                # defaults keep pre-B chunks unchanged).
                "is_superseded": chunk.get("is_superseded", False),
                "superseded_by": chunk.get("superseded_by"),
                "is_historical": chunk.get("is_historical", False),
            }
            for i, chunk in enumerate(chunks)
        ]
        trace: dict = {
            "retrieval": {
                "chunks_considered": len(chunks),
                "source_type_hint": source_type_hint,
                "candidates": candidates,
                # B fills knowledge_as_of/historical_pool_size; C fills
                # firm_knowledge_used. A defaults every one it owns the shape of.
                "knowledge_as_of": knowledge_as_of,
                "historical_pool_size": sum(
                    1 for c in chunks if c.get("is_historical", False)
                ),
                "firm_knowledge_used": firm_knowledge_used,
            },
            "generation": {
                "model": routed,
                "confidence": confidence,
                "input_tokens": stats.get("input_tokens"),
                "output_tokens": stats.get("output_tokens"),
            },
        }
        # trace.firm / trace.session are emitted only when the merged input dict
        # is non-empty (B and C merge their fragments before calling this).
        if firm:
            trace["firm"] = firm
        if session:
            trace["session"] = session
        return trace

    def _parse_citations(self, answer: str, chunks: list[dict]) -> list[dict]:
        cited_numbers = {int(n) for n in CITATION_PATTERN.findall(answer)}
        citations = []
        for n in sorted(cited_numbers):
            if 1 <= n <= len(chunks):
                chunk = chunks[n - 1]
                last_scraped_at = chunk.get("last_scraped_at")
                citations.append(
                    {
                        "citation": chunk["citation"],
                        "url": chunk["source_url"],
                        "excerpt": self._trim_excerpt(chunk["content"]),
                        "source_object_key": chunk.get("source_object_key"),
                        "last_scraped_at": last_scraped_at.isoformat() if last_scraped_at else None,
                    }
                )
        return citations

    @staticmethod
    def _cited_firm_citations(citations: list[dict]) -> list[str]:
        """The subset of parsed citations that are firm-knowledge sources (Task
        C5) — used both for ``trace.retrieval.firm_knowledge_used`` and to pick
        the firm chunks whose usage_count should be incremented."""
        return [
            c["citation"]
            for c in citations
            if c["citation"].startswith("Firm knowledge:")
        ]

    @staticmethod
    def _cited_firm_ids(citations: list[dict], chunks: list[dict]) -> list[str]:
        """firm_knowledge row ids for the CITED firm chunks (Task C5). Matches
        cited firm citations back to their source chunk to recover the ``id``
        that ``firm_search`` carries through the VectorHit."""
        cited = {
            c["citation"]
            for c in citations
            if c["citation"].startswith("Firm knowledge:")
        }
        return [
            chunk["id"]
            for chunk in chunks
            if chunk.get("id") is not None
            and chunk.get("citation", "").startswith("Firm knowledge:")
            and chunk["citation"] in cited
        ]

    @staticmethod
    async def _increment_firm_usage(client_id: str, item_ids: list[str]) -> None:
        """Best-effort usage_count bump for the CITED firm chunks (Task C5). Runs
        the sync repo call in a thread and swallows+logs any error so the answer
        flow is never failed by a usage-count write."""
        if not item_ids:
            return
        import asyncio

        from taxflow.providers import get_relational_data

        try:
            await asyncio.to_thread(
                get_relational_data().firm_knowledge.increment_usage,
                client_id,
                item_ids,
            )
        except Exception as e:  # noqa: BLE001 - usage-count is best-effort
            logger.warning(
                "firm knowledge usage_count increment failed for client_id=%s: %s",
                client_id,
                e,
            )

    @staticmethod
    async def _firm_usage_trend(client_id: str) -> dict | None:
        """Best-effort firm-knowledge usage trend (Task C6) for
        ``trace.firm.usage_trend`` — ``{quarter_count, prior_count}`` comparing
        firm_knowledge usage this quarter vs the prior quarter. Runs the sync
        repo read in a thread and returns None on ANY error (the trace then
        simply omits the trend), so it never fails the answer flow.
        """
        import asyncio

        from taxflow.providers import get_relational_data

        try:
            return await asyncio.to_thread(
                get_relational_data().firm_knowledge.usage_trend, client_id
            )
        except Exception as e:  # noqa: BLE001 - usage_trend is best-effort
            logger.warning(
                "firm knowledge usage_trend failed for client_id=%s: %s",
                client_id,
                e,
            )
            return None

    async def _build_firm_fragment(
        self, client: dict | None, client_id: str
    ) -> dict:
        """Assemble the C-owned ``trace.firm`` fragment (Task C6): the profile/
        voice booleans + summary from the client row, plus the usage_trend from
        the repo. Returns an empty dict when there is nothing to report, so the
        merge with B's firm_items fragment leaves trace.firm absent unless one
        side has real content.
        """
        fragment = build_firm_profile_fragment(client)
        if fragment:
            trend = await self._firm_usage_trend(client_id)
            if trend is not None:
                fragment["usage_trend"] = trend
        return fragment

    async def _assemble_answer_trace(
        self,
        *,
        chunks: list[dict],
        citations: list[dict],
        source_type_hint: list[str] | None,
        routed: str,
        stats: dict,
        confidence: float,
        client: dict | None,
        client_id: str,
        prior_turns_used: int,
        client_ref: str | None,
    ) -> dict:
        """Assemble the answer-flow trace shared by ``run`` and
        ``regenerate_with_feedback`` (Task B3 + C6).

        B's ``firm_items``/``firm_items_used`` fragment is MERGED with C's
        profile/voice/usage_trend fragment (disjoint keys) so neither side
        overwrites the other (co-ownership of ``trace.firm``); the block is
        emitted only when either side has real content. Also computes the
        freshness stamp and the session fragment, mirroring the ``graph.generate``
        node's merge so all three assembly points stay in step.
        """
        firm_used = self._cited_firm_citations(citations)
        knowledge_as_of = _compute_knowledge_as_of(chunks, citations)
        firm_fragment = await self._build_firm_fragment(client, client_id)
        firm_items = build_firm_items(chunks, citations)
        if firm_items["firm_items"]:
            firm_fragment.update(firm_items)
        session_fragment = build_session_fragment(
            prior_turns_used,
            self._engagement_memos_used(chunks),
            client_ref,
        )
        return self._build_trace(
            chunks, citations, source_type_hint, routed, stats, confidence,
            firm=firm_fragment or None,
            session=session_fragment,
            knowledge_as_of=knowledge_as_of,
            firm_knowledge_used=firm_used or None,
        )

    async def _load_session_history(self, client_id: str, session_id: str) -> list[dict]:
        """Load the last N prior turns for THIS (client_id, session_id) (Task D3).

        Auto-injection is scoped to the same session AND the same client: the
        repo query pins BOTH client_id and session_id, so context never bleeds
        across sessions/engagements or across clients. Returns oldest-first
        {question, answer} turns; full answers are truncated at read time by
        build_session_block. Returns [] on any DB error (session memory is best-
        effort, never fails the query).
        """
        import asyncio

        import psycopg2

        from taxflow.providers import get_relational_data

        try:
            rows = await asyncio.to_thread(
                get_relational_data().queries.list_session_history,
                client_id,
                session_id,
                settings.SESSION_HISTORY_N,
            )
        except (psycopg2.Error, OSError) as e:
            logger.warning(
                "session history load failed for client_id=%s session_id=%s: %s",
                client_id,
                session_id,
                e,
            )
            return []

        # DESC from SQL -> reverse to oldest-first for a natural conversation order.
        return [
            {"question": r["question"], "answer": r["final_answer"]} for r in reversed(rows)
        ]

    async def _build_steering(
        self,
        question: str,
        client_id: str,
        client: dict | None,
        session_id: str | None,
    ) -> tuple[str, list[str] | None, int]:
        """Assemble the advisory steering block (profile + session memory) and the
        source_type soft-boost hint (Tasks D1/D2/D3). Threaded into run() and the
        graph's build_steering node.

        Task C6: also returns the count of prior session turns loaded into the
        "conversation so far" block (previously computed then discarded). Callers
        thread it onto ``trace.session.prior_turns_used`` so the "why this answer?"
        UI can show how much conversational context steered the answer.
        """
        profile = build_client_profile(client)
        history: list[dict] = []
        if settings.SESSION_MEMORY_ENABLED and session_id:
            history = await self._load_session_history(client_id, session_id)
        session_block = build_session_block(history)
        steering = "\n\n".join(part for part in (profile, session_block) if part)

        active_modules = client.get("active_modules") if client else None
        source_type_hint = derive_source_type_hint(question, active_modules)
        return steering, source_type_hint, len(history)

    @staticmethod
    def _engagement_memos_used(chunks: list[dict]) -> int:
        """Count the engagement-context memos merged into the retrieved pool
        (Task C6). Engagement hits carry a ``"Engagement memo: ..."`` citation
        (see the vector-store ``engagement_search`` adapter), so they are counted
        by that prefix for ``trace.session.engagement_memos_used``.
        """
        return sum(
            1
            for chunk in chunks
            if chunk.get("citation", "").startswith("Engagement memo:")
        )

    async def _prepare(
        self,
        question: str,
        client_id: str,
        embedding: list[float] | None,
        client: dict | None,
        session_id: str | None,
        pool_scale: int = 1,
        client_ref: str | None = None,
    ) -> tuple[str, str, list[dict], dict, list[str] | None, int]:
        """Shared front half of every generation path: build the advisory steering
        block + source_type hint, retrieve the merged context, and render the
        context string. Returns (context, steering, chunks, signals,
        source_type_hint, prior_turns_used) - the hint is threaded back out so
        callers can record it on the answer-flow trace, and prior_turns_used (Task
        C6) so callers can populate trace.session. run() and
        regenerate_with_feedback() both start here so profile injection, session
        memory and embedding threading stay in one place.

        ``pool_scale`` (Task C3) is threaded into retrieval so a reviewer-driven
        widened corrective pass can look at a broader pool for this call only.
        """
        steering, source_type_hint, prior_turns_used = await self._build_steering(
            question, client_id, client, session_id
        )
        chunks, signals = await self._retrieve_context(
            question,
            client_id,
            embedding=embedding,
            source_type_hint=source_type_hint,
            pool_scale=pool_scale,
            client_ref=client_ref,
        )
        context = self._build_context_string(chunks)
        return context, steering, chunks, signals, source_type_hint, prior_turns_used

    @staticmethod
    def _model_for(routed: str) -> str:
        """Map a route_model() decision ("haiku"/"sonnet") to the configured model id."""
        return settings.ANTHROPIC_SONNET_MODEL if routed == "sonnet" else settings.ANTHROPIC_HAIKU_MODEL

    async def run(
        self,
        question: str,
        client_id: str,
        embedding: list[float] | None = None,
        client: dict | None = None,
        session_id: str | None = None,
        client_ref: str | None = None,
    ) -> dict:
        start = time.monotonic()
        context, steering, chunks, signals, source_type_hint, prior_turns_used = (
            await self._prepare(
                question, client_id, embedding, client, session_id,
                client_ref=client_ref,
            )
        )

        # Pre-generation model routing (Task A3): decide the model from retrieval
        # signals BEFORE the single generation call. Exactly one _generate per query.
        routed = route_model(signals)
        model = self._model_for(routed)

        answer, stats = await self._generate(question, context, model, steering=steering)
        citations = self._parse_citations(answer, chunks)
        confidence = self._estimate_confidence(answer, chunks, citations)

        # Task C5: bump usage_count for the CITED firm chunks (best-effort) and
        # surface the cited firm citations on the trace.
        await self._increment_firm_usage(
            client_id, self._cited_firm_ids(citations, chunks)
        )

        result = {
            "answer": answer,
            "citations": citations,
            "confidence": confidence,
            "model_used": routed,
            "chunks_retrieved": len(chunks),
            **stats,
            "wall_time_ms": int((time.monotonic() - start) * 1000),
            "trace": await self._assemble_answer_trace(
                chunks=chunks,
                citations=citations,
                source_type_hint=source_type_hint,
                routed=routed,
                stats=stats,
                confidence=confidence,
                client=client,
                client_id=client_id,
                prior_turns_used=prior_turns_used,
                client_ref=client_ref,
            ),
        }
        # Eval-only (default off): echo the EXACT rendered context the answer was
        # generated from, so the LLM-as-judge grades against the real sources
        # rather than a re-derived candidate list. Never emitted in production.
        if settings.EVAL_CAPTURE_CONTEXT:
            result["eval_context"] = context
        return result

    async def regenerate_with_feedback(
        self,
        question: str,
        client_id: str,
        issues: list[dict],
        embedding: list[float] | None = None,
        client: dict | None = None,
        session_id: str | None = None,
        widen: bool = False,
        client_ref: str | None = None,
    ) -> dict:
        """ONE bounded corrective regeneration pass (Task C3).

        Called at most once, only when verification flagged the answer. It appends
        the verifier's issues to the context and regenerates with Sonnet (the
        stronger model, since the first pass was found wanting). There is NO loop:
        the caller invokes this exactly once and does not re-verify-and-retry.

        The corrective pass reuses the same advisory profile/session steering and
        source_type soft-boost hint (Tasks D1/D2/D3) so the retry stays personalised.

        Task C3: when ``widen`` is True and ``REVIEWER_WIDEN_ENABLED``, retrieval
        is re-run with ``pool_scale=2`` — a broader candidate pool for THIS one
        corrective call, threaded as a parameter so the global pool ``settings``
        are never mutated (concurrent requests keep their own pool sizes). The
        return carries ``re_retrieval`` describing whether the widen fired and
        sets ``re_retrieved`` so A1's ``_build_final_trace`` sees ``fired=True``.
        """
        widened = widen and settings.REVIEWER_WIDEN_ENABLED
        pool_scale = 2 if widened else 1
        context, steering, chunks, _signals, source_type_hint, prior_turns_used = (
            await self._prepare(
                question, client_id, embedding, client, session_id,
                pool_scale=pool_scale, client_ref=client_ref,
            )
        )

        issue_lines = "\n".join(
            f"- Claim: {i.get('claim', '')}\n  Problem: {i.get('issue', '')}\n"
            f"  Source says: {i.get('source_says', '')}\n"
            f"  Correction: {i.get('suggested_correction', '')}"
            for i in issues
        )
        corrective_context = (
            f"{context}\n\n"
            "A prior draft of this answer was reviewed and the following issues were "
            "raised. Produce a corrected answer that resolves each of them, still "
            "citing only the provided sources:\n"
            f"{issue_lines}"
        )

        answer, stats = await self._generate(
            question, corrective_context, settings.ANTHROPIC_SONNET_MODEL, steering=steering
        )
        citations = self._parse_citations(answer, chunks)
        confidence = self._estimate_confidence(answer, chunks, citations)
        re_retrieval = (
            {"fired": True, "reason": "reviewer_flag"} if widened else {"fired": False}
        )
        return {
            "answer": answer,
            "citations": citations,
            "confidence": confidence,
            "model_used": "sonnet",
            "re_retrieved": widened,
            "re_retrieval": re_retrieval,
            **stats,
            "trace": await self._assemble_answer_trace(
                chunks=chunks,
                citations=citations,
                source_type_hint=source_type_hint,
                routed="sonnet",
                stats=stats,
                confidence=confidence,
                client=client,
                client_id=client_id,
                prior_turns_used=prior_turns_used,
                client_ref=client_ref,
            ),
        }
