import re
import time

from anthropic import AsyncAnthropic

from taxflow.config import settings
from taxflow.services.knowledge.retrieval import (
    generate_candidates,
    rerank_candidates,
)

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


class ResearchAgent:
    def __init__(self) -> None:
        self._client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def _retrieve_context(
        self, question: str, client_id: str, embedding: list[float] | None = None
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

        Returns (chunks, signals). Routing signals (Task A3) are derived from the
        GLOBAL candidate pool only: firm chunks carry a weighted score on a
        different scale, so mixing them in would distort the RRF-based thresholds.
        """
        global_candidates = await generate_candidates(question, embedding=embedding)
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
        except Exception:  # firm knowledge is optional; never fail the query over it
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

    async def _generate(self, question: str, context: str, model: str) -> tuple[str, dict]:
        response = await self._client.messages.create(
            model=model,
            max_tokens=1500,
            temperature=0,
            system=_system_blocks(),
            messages=[{"role": "user", "content": f"Question: {question}\n\nSource documents:\n{context}"}],
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

    async def run(
        self,
        question: str,
        client_id: str,
        filters: dict | None = None,
        embedding: list[float] | None = None,
    ) -> dict:
        start = time.monotonic()
        chunks, signals = await self._retrieve_context(question, client_id, embedding=embedding)
        context = self._build_context_string(chunks)

        # Pre-generation model routing (Task A3): decide the model from retrieval
        # signals BEFORE the single generation call. Exactly one _generate per query.
        routed = route_model(signals)
        model = settings.ANTHROPIC_SONNET_MODEL if routed == "sonnet" else settings.ANTHROPIC_HAIKU_MODEL

        answer, stats = await self._generate(question, context, model)
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

    async def run_stream(self, question: str, client_id: str, embedding: list[float] | None = None):
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
        """
        chunks, signals = await self._retrieve_context(question, client_id, embedding=embedding)
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
            messages=[{"role": "user", "content": f"Question: {question}\n\nSource documents:\n{context}"}],
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
    ) -> dict:
        """ONE bounded corrective regeneration pass (Task C3).

        Called at most once, only when verification flagged the answer. It appends
        the verifier's issues to the context and regenerates with Sonnet (the
        stronger model, since the first pass was found wanting). There is NO loop:
        the caller invokes this exactly once and does not re-verify-and-retry.
        """
        chunks, _signals = await self._retrieve_context(question, client_id, embedding=embedding)
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
            question, corrective_context, settings.ANTHROPIC_SONNET_MODEL
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
