import logging
import re
import time

from anthropic import AsyncAnthropic

from taxflow.config import settings
from taxflow.services.knowledge.retrieval import (
    apply_source_type_boost,
    generate_candidates,
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
7. End with a "Sources" section listing all cited documents.
"""

CONTEXT_TOKEN_LIMIT = 60_000
CITATION_PATTERN = re.compile(r"\[(\d+)\]")


def _system_blocks() -> list[dict] | str:
    """Return the system prompt as a cacheable content block (Task B1).

    anthropic>=0.39 supports cache_control. The system prompt is large and fully
    static, so it forms a stable cacheable prefix; marking it ephemeral lets
    repeat calls (Haiku + Sonnet, back-to-back queries within the 5-min TTL) read
    it from cache at ~10% of the input price. When disabled we fall back to the
    plain string form the API also accepts.
    """
    if not settings.PROMPT_CACHE_ENABLED:
        return SYSTEM_PROMPT
    return [
        {
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def route_model(signals: dict) -> str:
    """Pick "haiku" or "sonnet" BEFORE the single generation call (Task A3).

    Uses only retrieval signals available WITHOUT any LLM call, so we never pay
    for a throwaway generation just to decide the model:
      - num_chunks:  how many chunks retrieval returned.
      - top_score:   the top RRF score (or re-rank score once C1 lands) over the
                     global candidate pool.
      - insufficient: True when hybrid search returned nothing (the "insufficient
                     information" retrieval situation).
      - rerank_top_score: optional; from C1's re-ranker when present. When given it
                     is treated the same way as top_score for the strong-retrieval
                     gate.

    Strong, confident retrieval -> Haiku is enough. Anything weak or ambiguous
    routes to Sonnet: we deliberately bias toward Sonnet so a mis-tuned router
    never silently sends a hard question to the weaker model.
    """
    if signals.get("insufficient") or signals.get("num_chunks", 0) == 0:
        return "sonnet"

    num_chunks = signals.get("num_chunks", 0)
    top_score = signals.get("top_score", 0.0) or 0.0
    rerank_top = signals.get("rerank_top_score")
    if rerank_top is not None:
        top_score = max(top_score, rerank_top)

    strong = (
        num_chunks >= settings.ROUTE_MIN_STRONG_CHUNKS
        and top_score >= settings.ROUTE_MIN_TOP_RRF_SCORE
    )
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
    lines = ["Conversation so far (prior turns in this session, for context only):"]
    for turn in history:
        q = (turn.get("question") or "").strip()
        a = (turn.get("answer") or "").strip()
        summary = a[: settings.SESSION_SUMMARY_CHARS]
        if len(a) > settings.SESSION_SUMMARY_CHARS:
            summary += "…"
        lines.append(f"- Q: {q}\n  A: {summary}")
    return "\n".join(lines)


class ResearchAgent:
    def __init__(self) -> None:
        self._client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def _retrieve_context(
        self,
        question: str,
        client_id: str,
        embedding: list[float] | None = None,
        source_type_hint: list[str] | None = None,
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
            question, source_types=sql_source_types, embedding=embedding
        )
        if settings.SOURCE_TYPE_FILTER_MODE != "hard":
            global_candidates = apply_source_type_boost(global_candidates, source_type_hint)
        firm_candidates = await self._firm_knowledge_search(
            question, client_id, top_k=settings.RETRIEVAL_FIRM_POOL, embedding=embedding
        )

        # Routing signals from the GLOBAL pool only (before merging in firm docs).
        signals = {
            "num_chunks": len(global_candidates),
            "top_score": max((c["score"] for c in global_candidates), default=0.0),
            "insufficient": len(global_candidates) == 0,
        }

        # Merge into one pool. Firm chunks already carry score = sim * FIRM_CHUNK_WEIGHT
        # (see _firm_knowledge_search), so they participate in the ranking instead
        # of being appended after global truncation.
        merged = global_candidates[: settings.RETRIEVAL_GLOBAL_POOL] + firm_candidates
        merged.sort(key=lambda c: c.get("score", 0.0), reverse=True)

        # If C1's re-rank is active, run the combined pool (global + firm) through
        # the same re-ranker so firm chunks are judged on relevance too.
        reranked = await rerank_candidates(question, merged)

        chunks = reranked[: settings.RETRIEVAL_TOP_K]

        # Surface the re-rank top score to the router (Task A3 accepts it) so a
        # strong LLM-judged relevance can promote to Haiku.
        rerank_scores = [c["rerank_score"] for c in chunks if "rerank_score" in c]
        if rerank_scores:
            signals["rerank_top_score"] = max(rerank_scores)

        return chunks, signals

    async def _firm_knowledge_search(
        self, question: str, client_id: str, top_k: int, embedding: list[float] | None = None
    ) -> list[dict]:
        import asyncio

        import psycopg2
        import psycopg2.extras

        from taxflow.db import get_pg_conn
        from taxflow.services.knowledge.embedder import embed

        # Reuse the single query embedding when the caller passed it (Task A4);
        # only embed here if invoked standalone.
        query_embedding = embedding if embedding is not None else await embed(question)

        def _search() -> list[dict]:
            with get_pg_conn() as conn:
                # SET LOCAL needs an explicit transaction on the pooled connection
                # (Task A5); the psycopg2 connection context manager provides one.
                with conn:
                    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                    cur.execute("SET LOCAL ivfflat.probes = %s", (settings.IVFFLAT_PROBES,))
                    cur.execute(
                        """
                        SELECT id, file_name, content,
                               1 - (embedding <=> %s::vector) AS sim
                        FROM firm_knowledge
                        WHERE client_id = %s AND embedding IS NOT NULL
                        ORDER BY embedding <=> %s::vector
                        LIMIT %s
                        """,
                        (query_embedding, client_id, query_embedding, top_k),
                    )
                    rows = cur.fetchall()
                    cur.close()
                    return list(rows)

        try:
            rows = await asyncio.to_thread(_search)
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
        return [
            {
                "id": str(r["id"]),
                "citation": f"Firm knowledge: {r['file_name']}",
                "content": r["content"],
                "source_url": "",
                "source_object_key": None,
                "score": float(r["sim"]) * settings.FIRM_CHUNK_WEIGHT,
            }
            for r in rows
        ]

    def _build_context_string(self, chunks: list[dict]) -> str:
        parts = []
        for i, chunk in enumerate(chunks, start=1):
            parts.append(
                f"[{i}] Citation: {chunk['citation']}\n"
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
        response = await self._client.messages.create(
            model=model,
            max_tokens=1500,
            temperature=0,
            system=_system_blocks(),
            messages=[{"role": "user", "content": self._user_content(question, context, steering)}],
        )
        answer = "".join(block.text for block in response.content if block.type == "text")
        usage = response.usage
        # Capture prompt-cache token usage (Task B1) alongside the existing token
        # reads. getattr keeps this safe against older SDKs that don't expose the
        # cache fields; input/output token reads are unchanged.
        stats = {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
            "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        }
        return answer, stats

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

    def _parse_citations(self, answer: str, chunks: list[dict]) -> list[dict]:
        cited_numbers = {int(n) for n in CITATION_PATTERN.findall(answer)}
        citations = []
        for n in sorted(cited_numbers):
            if 1 <= n <= len(chunks):
                chunk = chunks[n - 1]
                citations.append(
                    {
                        "citation": chunk["citation"],
                        "url": chunk["source_url"],
                        "excerpt": chunk["content"][:200],
                        "source_object_key": chunk.get("source_object_key"),
                    }
                )
        return citations

    async def _load_session_history(self, client_id: str, session_id: str) -> list[dict]:
        """Load the last N prior turns for THIS (client_id, session_id) (Task D3).

        Auto-injection is scoped to the same session AND the same client: the
        WHERE clause pins BOTH client_id and session_id, so context never bleeds
        across sessions/engagements or across clients. Returns oldest-first
        {question, answer} turns; full answers are truncated at read time by
        build_session_block. Returns [] on any DB error (session memory is best-
        effort, never fails the query).
        """
        import asyncio

        import psycopg2
        import psycopg2.extras

        from taxflow.db import get_pg_conn

        def _query() -> list[dict]:
            with get_pg_conn() as conn:
                with conn:
                    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                    cur.execute(
                        """
                        SELECT question, final_answer
                        FROM queries
                        WHERE client_id = %s AND session_id = %s
                          AND status = 'completed' AND final_answer IS NOT NULL
                        ORDER BY created_at DESC
                        LIMIT %s
                        """,
                        (client_id, session_id, settings.SESSION_HISTORY_N),
                    )
                    rows = cur.fetchall()
                    cur.close()
                    return list(rows)

        try:
            rows = await asyncio.to_thread(_query)
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
    ) -> tuple[str, list[str] | None]:
        """Assemble the advisory steering block (profile + session memory) and the
        source_type soft-boost hint (Tasks D1/D2/D3). Threaded into run/run_stream.
        """
        profile = build_client_profile(client)
        history: list[dict] = []
        if settings.SESSION_MEMORY_ENABLED and session_id:
            history = await self._load_session_history(client_id, session_id)
        session_block = build_session_block(history)
        steering = "\n\n".join(part for part in (profile, session_block) if part)

        active_modules = client.get("active_modules") if client else None
        source_type_hint = derive_source_type_hint(question, active_modules)
        return steering, source_type_hint

    async def run(
        self,
        question: str,
        client_id: str,
        filters: dict | None = None,
        embedding: list[float] | None = None,
        client: dict | None = None,
        session_id: str | None = None,
    ) -> dict:
        start = time.monotonic()
        steering, source_type_hint = await self._build_steering(
            question, client_id, client, session_id
        )
        chunks, signals = await self._retrieve_context(
            question, client_id, embedding=embedding, source_type_hint=source_type_hint
        )
        context = self._build_context_string(chunks)

        # Pre-generation model routing (Task A3): decide the model from retrieval
        # signals BEFORE the single generation call. Exactly one _generate per query.
        routed = route_model(signals)
        model = settings.ANTHROPIC_SONNET_MODEL if routed == "sonnet" else settings.ANTHROPIC_HAIKU_MODEL

        answer, stats = await self._generate(question, context, model, steering=steering)
        citations = self._parse_citations(answer, chunks)
        confidence = self._estimate_confidence(answer, chunks, citations)

        return {
            "answer": answer,
            "citations": citations,
            "confidence": confidence,
            "model_used": routed,
            "chunks_retrieved": len(chunks),
            "input_tokens": stats["input_tokens"],
            "output_tokens": stats["output_tokens"],
            "cache_read_input_tokens": stats["cache_read_input_tokens"],
            "cache_creation_input_tokens": stats["cache_creation_input_tokens"],
            "wall_time_ms": int((time.monotonic() - start) * 1000),
        }

    async def run_stream(
        self,
        question: str,
        client_id: str,
        embedding: list[float] | None = None,
        client: dict | None = None,
        session_id: str | None = None,
    ):
        """Yields token events, then a final citations/metrics event.

        Task C2: the streaming path now applies the SAME pre-generation routing as
        run() (route_model from retrieval signals) instead of always using Haiku,
        so interactive users get the same model the batch path would pick. The
        model is decided UP FRONT (streaming can't upgrade mid-stream), keeping one
        consistent policy across run() and run_stream().

        Events:
          {"type": "token", "text": ...}   (repeated while streaming)
          {"type": "final", "citations": [...], "answer": ..., "confidence": ...,
           "model_used": ..., "input_tokens": ..., "output_tokens": ...,
           "cache_read_input_tokens": ..., "cache_creation_input_tokens": ...,
           "chunks_retrieved": ...}

        Tasks D1/D2/D3: the same advisory client-profile + session-memory steering
        and source_type soft-boost hint used by run() are applied here, so the
        interactive stream path is personalised identically to the batch path.
        """
        steering, source_type_hint = await self._build_steering(
            question, client_id, client, session_id
        )
        chunks, signals = await self._retrieve_context(
            question, client_id, embedding=embedding, source_type_hint=source_type_hint
        )
        context = self._build_context_string(chunks)

        routed = route_model(signals)
        model = settings.ANTHROPIC_SONNET_MODEL if routed == "sonnet" else settings.ANTHROPIC_HAIKU_MODEL

        answer_parts: list[str] = []
        usage = None
        async with self._client.messages.stream(
            model=model,
            max_tokens=1500,
            temperature=0,
            system=_system_blocks(),
            messages=[{"role": "user", "content": self._user_content(question, context, steering)}],
        ) as stream:
            async for text in stream.text_stream:
                answer_parts.append(text)
                yield {"type": "token", "text": text}
            final_message = await stream.get_final_message()
            usage = final_message.usage

        answer = "".join(answer_parts)
        citations = self._parse_citations(answer, chunks)
        confidence = self._estimate_confidence(answer, chunks, citations)

        # Task C5: surface model/confidence/token metrics on the final event so the
        # SSE route can persist them on the queries row (parity with POST /query).
        yield {
            "type": "final",
            "citations": citations,
            "answer": answer,
            "confidence": confidence,
            "model_used": routed,
            "chunks_retrieved": len(chunks),
            "input_tokens": getattr(usage, "input_tokens", 0) if usage else 0,
            "output_tokens": getattr(usage, "output_tokens", 0) if usage else 0,
            "cache_read_input_tokens": (getattr(usage, "cache_read_input_tokens", 0) or 0) if usage else 0,
            "cache_creation_input_tokens": (getattr(usage, "cache_creation_input_tokens", 0) or 0) if usage else 0,
        }

    async def regenerate_with_feedback(
        self,
        question: str,
        client_id: str,
        issues: list[dict],
        embedding: list[float] | None = None,
        client: dict | None = None,
        session_id: str | None = None,
    ) -> dict:
        """ONE bounded corrective regeneration pass (Task C3).

        Called at most once, only when verification flagged the answer. It appends
        the verifier's issues to the context and regenerates with Sonnet (the
        stronger model, since the first pass was found wanting). There is NO loop:
        the caller invokes this exactly once and does not re-verify-and-retry.

        The corrective pass reuses the same advisory profile/session steering and
        source_type soft-boost hint (Tasks D1/D2/D3) so the retry stays personalised.
        """
        steering, source_type_hint = await self._build_steering(
            question, client_id, client, session_id
        )
        chunks, _signals = await self._retrieve_context(
            question, client_id, embedding=embedding, source_type_hint=source_type_hint
        )
        context = self._build_context_string(chunks)

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
        return {
            "answer": answer,
            "citations": citations,
            "confidence": confidence,
            "model_used": "sonnet",
            "input_tokens": stats["input_tokens"],
            "output_tokens": stats["output_tokens"],
            "cache_read_input_tokens": stats["cache_read_input_tokens"],
            "cache_creation_input_tokens": stats["cache_creation_input_tokens"],
        }
