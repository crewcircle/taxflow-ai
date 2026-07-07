import re
import time

from anthropic import AsyncAnthropic

from taxflow.config import settings
from taxflow.db import get_supabase_client
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

        sb = get_supabase_client()
        embedding_result = await hybrid_search(question, top_k=3)  # placeholder shared embed call
        firm_chunks = (
            sb.table("firm_knowledge")
            .select("id, content")
            .eq("client_id", client_id)
            .limit(3)
            .execute()
        )

        merged = list(global_chunks)
        for row in firm_chunks.data:
            merged.append(
                {
                    "id": row["id"],
                    "citation": "Firm knowledge",
                    "content": row["content"],
                    "source_url": "",
                    "score": 1.5,
                }
            )
        return merged[:10]

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

    async def _score_confidence(self, question: str, answer: str, citation_count: int) -> float:
        response = await self._client.messages.create(
            model=settings.ANTHROPIC_HAIKU_MODEL,
            max_tokens=10,
            temperature=0,
            system=(
                "Rate the confidence of this answer 0.0-1.0 based on: source coverage, "
                "citation count, question specificity, source recency. Return only a float."
            ),
            messages=[
                {
                    "role": "user",
                    "content": f"Question: {question}\nAnswer: {answer}\nSources used: {citation_count}",
                }
            ],
        )
        text = "".join(block.text for block in response.content if block.type == "text").strip()
        try:
            return float(text)
        except ValueError:
            return 0.5

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
        confidence = await self._score_confidence(question, answer, len(chunks))

        if confidence < settings.HAIKU_CONFIDENCE_THRESHOLD:
            model_used = "sonnet"
            answer, input_tokens, output_tokens = await self._generate(
                question, context, settings.ANTHROPIC_SONNET_MODEL
            )
            confidence = await self._score_confidence(question, answer, len(chunks))

        citations = self._parse_citations(answer, chunks)

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
        chunks = await self._retrieve_context(question, client_id)
        context = self._build_context_string(chunks)

        async with self._client.messages.stream(
            model=settings.ANTHROPIC_HAIKU_MODEL,
            max_tokens=1500,
            temperature=0,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Question: {question}\n\nSource documents:\n{context}"}],
        ) as stream:
            async for text in stream.text_stream:
                yield text
