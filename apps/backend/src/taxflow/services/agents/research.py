import re
import time

from anthropic import AsyncAnthropic

from taxflow.config import settings
from taxflow.services.knowledge.retrieval import hybrid_search

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


class ResearchAgent:
    def __init__(self) -> None:
        self._client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def _retrieve_context(self, question: str, client_id: str) -> list[dict]:
        global_chunks = await hybrid_search(question, top_k=8)
        firm_chunks = await self._firm_knowledge_search(question, client_id, top_k=2)
        return (global_chunks + firm_chunks)[:10]

    async def _firm_knowledge_search(self, question: str, client_id: str, top_k: int) -> list[dict]:
        import asyncio

        import psycopg2.extras

        from taxflow.db import get_pg_conn
        from taxflow.services.knowledge.embedder import embed

        query_embedding = await embed(question)

        def _search() -> list[dict]:
            with get_pg_conn() as conn:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
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

        # 1.5x weight: firm documents are more specific to the client than global sources
        return [
            {
                "id": str(r["id"]),
                "citation": f"Firm knowledge: {r['file_name']}",
                "content": r["content"],
                "source_url": "",
                "score": float(r["sim"]) * 1.5,
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

    async def _generate(self, question: str, context: str, model: str) -> tuple[str, int, int]:
        response = await self._client.messages.create(
            model=model,
            max_tokens=1500,
            temperature=0,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Question: {question}\n\nSource documents:\n{context}"}],
        )
        answer = "".join(block.text for block in response.content if block.type == "text")
        return answer, response.usage.input_tokens, response.usage.output_tokens

    def _estimate_confidence(self, answer: str, chunks: list[dict], citations: list[dict]) -> float:
        """Deterministic confidence from retrieval/citation signals. Replaces the LLM
        self-grading call, which was badly miscalibrated (0.05 on correct answers) and
        escalated 26/30 accuracy questions to Sonnet for no accuracy gain."""
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

    async def run(self, question: str, client_id: str, filters: dict | None = None) -> dict:
        start = time.monotonic()
        chunks = await self._retrieve_context(question, client_id)
        context = self._build_context_string(chunks)

        model_used = "haiku"
        answer, input_tokens, output_tokens = await self._generate(
            question, context, settings.ANTHROPIC_HAIKU_MODEL
        )
        citations = self._parse_citations(answer, chunks)
        confidence = self._estimate_confidence(answer, chunks, citations)

        if confidence < settings.HAIKU_CONFIDENCE_THRESHOLD:
            model_used = "sonnet"
            answer, input_tokens, output_tokens = await self._generate(
                question, context, settings.ANTHROPIC_SONNET_MODEL
            )
            citations = self._parse_citations(answer, chunks)
            confidence = self._estimate_confidence(answer, chunks, citations)

        return {
            "answer": answer,
            "citations": citations,
            "confidence": confidence,
            "model_used": model_used,
            "chunks_retrieved": len(chunks),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "wall_time_ms": int((time.monotonic() - start) * 1000),
        }

    async def run_stream(self, question: str, client_id: str):
        """Yields {"type": "token", "text": ...} events, then a final
        {"type": "final", "citations": [...]} event."""
        chunks = await self._retrieve_context(question, client_id)
        context = self._build_context_string(chunks)

        answer_parts: list[str] = []
        async with self._client.messages.stream(
            model=settings.ANTHROPIC_HAIKU_MODEL,
            max_tokens=1500,
            temperature=0,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Question: {question}\n\nSource documents:\n{context}"}],
        ) as stream:
            async for text in stream.text_stream:
                answer_parts.append(text)
                yield {"type": "token", "text": text}

        citations = self._parse_citations("".join(answer_parts), chunks)
        yield {"type": "final", "citations": citations}
