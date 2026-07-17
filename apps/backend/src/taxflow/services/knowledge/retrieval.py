import asyncio
import re

import psycopg2
import psycopg2.extras

from taxflow.config import settings
from taxflow.services.knowledge.embedder import embed

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


def _semantic_search(embedding: list[float], source_types: list[str] | None) -> list[dict]:
    conn = psycopg2.connect(settings.DATABASE_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        """
        SELECT id, citation, content, source_url, source_object_key, last_scraped_at,
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
        SELECT id, citation, content, source_url, source_object_key, last_scraped_at,
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

    # Recency tie-breaker: two rulings can be near-equally relevant to a query
    # (e.g. TR 2020/4 and TR 2025/2 both "about thin capitalisation"), and with
    # no supersession metadata to lean on, pure relevance ranking has no way to
    # prefer the newer one. Nudge the score toward whichever is more recent.
    for doc_id, doc in docs.items():
        scores[doc_id] += _citation_year(doc["citation"]) * _RECENCY_WEIGHT_PER_YEAR

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    return [
        {
            "id": doc_id,
            "citation": docs[doc_id]["citation"],
            "content": docs[doc_id]["content"],
            "source_url": docs[doc_id]["source_url"],
            "source_object_key": docs[doc_id]["source_object_key"],
            "last_scraped_at": docs[doc_id]["last_scraped_at"],
            "score": score,
        }
        for doc_id, score in ranked
    ]
