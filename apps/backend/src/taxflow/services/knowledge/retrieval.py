import asyncio

import psycopg2
import psycopg2.extras

from taxflow.config import settings
from taxflow.services.knowledge.embedder import embed


def _semantic_search(embedding: list[float], source_types: list[str] | None) -> list[dict]:
    conn = psycopg2.connect(settings.DATABASE_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        """
        SELECT id, citation, content, source_url, source_object_key,
               1 - (embedding <=> %s::vector) AS cosine_sim
        FROM knowledge_chunks
        WHERE is_current = true
          AND (%s::text[] IS NULL OR source_type = ANY(%s))
        ORDER BY embedding <=> %s::vector
        LIMIT 20
        """,
        (embedding, source_types, source_types, embedding),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return list(rows)


def _text_search(query: str, source_types: list[str] | None) -> list[dict]:
    conn = psycopg2.connect(settings.DATABASE_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        """
        SELECT id, citation, content, source_url, source_object_key,
               ts_rank(to_tsvector('english', content), plainto_tsquery('english', %s)) AS text_rank
        FROM knowledge_chunks
        WHERE is_current = true
          AND to_tsvector('english', content) @@ plainto_tsquery('english', %s)
          AND (%s::text[] IS NULL OR source_type = ANY(%s))
        ORDER BY text_rank DESC
        LIMIT 20
        """,
        (query, query, source_types, source_types),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return list(rows)


async def hybrid_search(query: str, top_k: int = 10, source_types: list[str] | None = None) -> list[dict]:
    embedding = await embed(query)

    semantic, textual = await asyncio.gather(
        asyncio.to_thread(_semantic_search, embedding, source_types),
        asyncio.to_thread(_text_search, query, source_types),
    )

    scores: dict[str, float] = {}
    docs: dict[str, dict] = {}
    for rank, row in enumerate(semantic):
        scores[row["id"]] = scores.get(row["id"], 0.0) + 1 / (60 + rank)
        docs[row["id"]] = row
    for rank, row in enumerate(textual):
        scores[row["id"]] = scores.get(row["id"], 0.0) + 1 / (60 + rank)
        docs.setdefault(row["id"], row)

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    return [
        {
            "id": doc_id,
            "citation": docs[doc_id]["citation"],
            "content": docs[doc_id]["content"],
            "source_url": docs[doc_id]["source_url"],
            "source_object_key": docs[doc_id]["source_object_key"],
            "score": score,
        }
        for doc_id, score in ranked
    ]
