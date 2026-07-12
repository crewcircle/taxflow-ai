import asyncio
import re

import psycopg2
import tiktoken

from taxflow.config import settings
from taxflow.services.knowledge.embedder import embed_batch

_encoder = tiktoken.get_encoding("cl100k_base")

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def chunk_text(text: str, chunk_tokens: int | None = None, overlap_tokens: int | None = None) -> list[str]:
    """Split into ~chunk_tokens segments at sentence boundaries with token overlap."""
    chunk_tokens = chunk_tokens or settings.CHUNK_SIZE_TOKENS
    overlap_tokens = overlap_tokens or settings.CHUNK_OVERLAP_TOKENS

    sentences = SENTENCE_SPLIT.split(text)
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for sentence in sentences:
        sentence_tokens = len(_encoder.encode(sentence))
        if current and current_tokens + sentence_tokens > chunk_tokens:
            chunks.append(" ".join(current))
            # Carry overlap: keep trailing sentences up to overlap_tokens
            kept: list[str] = []
            kept_tokens = 0
            for s in reversed(current):
                s_tokens = len(_encoder.encode(s))
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


def _upsert_chunks(rows: list[tuple]) -> int:
    conn = psycopg2.connect(settings.DATABASE_URL)
    cur = conn.cursor()
    for row in rows:
        cur.execute(
            """
            INSERT INTO knowledge_chunks
                (source_type, source_url, source_title, citation, content, embedding,
                 chunk_index, token_count, effective_date, source_object_key, last_scraped_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (source_url, chunk_index) DO UPDATE SET
                content = EXCLUDED.content,
                embedding = EXCLUDED.embedding,
                token_count = EXCLUDED.token_count,
                source_object_key = EXCLUDED.source_object_key,
                last_scraped_at = now()
            """,
            row,
        )
    conn.commit()
    count = len(rows)
    cur.close()
    conn.close()
    return count


async def process_document(text: str, metadata: dict, source_object_key: str | None = None) -> int:
    """Chunk, embed, and upsert one document. Returns chunk count."""
    chunks = chunk_text(text)
    if not chunks:
        return 0

    embeddings = await embed_batch(chunks)

    rows = [
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
        )
        for index, (chunk, embedding) in enumerate(zip(chunks, embeddings))
    ]
    return await asyncio.to_thread(_upsert_chunks, rows)
