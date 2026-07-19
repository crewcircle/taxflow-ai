"""pgvector/Postgres adapter implementing
:class:`taxflow.ports.vectorstore.VectorStorePort` (Task A3).

All the Postgres-specific SQL lives here: the ``<=>`` cosine distance operator,
``ivfflat.probes`` tuning, and the full-text ``to_tsvector``/``plainto_tsquery``/
``ts_rank`` search. The synchronous psycopg2 work runs under
:func:`asyncio.to_thread` and uses the shared connection pool via
:func:`taxflow.db.get_pg_conn`. Callers get back plain :class:`VectorHit` dicts;
the RRF merge, source-type boost, firm weighting and re-rank logic stay in the
retrieval service (provider-agnostic).

The ``SET LOCAL ivfflat.probes`` statement only applies inside an explicit
transaction; on a pooled connection a bare ``SET LOCAL`` outside a transaction
silently no-ops. The psycopg2 connection context manager opens/commits one
transaction, so we scope the probes tuning and the vector SELECT together (CM
§3 / the SET-LOCAL-in-transaction fix).
"""

from __future__ import annotations

import asyncio

import psycopg2.extras

from taxflow.config import settings
from taxflow.db import get_pg_conn
from taxflow.ports.vectorstore import VectorHit


class PgVectorStore:
    """VectorStorePort adapter backed by Postgres + pgvector."""

    async def semantic_search(
        self,
        *,
        embedding: list[float],
        source_types: list[str] | None = None,
        limit: int = 40,
    ) -> list[VectorHit]:
        def _search() -> list[dict]:
            with get_pg_conn() as conn:
                # SET LOCAL only applies inside an explicit transaction; on a pooled
                # connection a bare SET LOCAL outside a transaction silently no-ops. The
                # psycopg2 connection context manager opens/commits one transaction, so we
                # scope the probes tuning and the vector SELECT together here.
                with conn:
                    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                    cur.execute("SET LOCAL ivfflat.probes = %s", (settings.IVFFLAT_PROBES,))
                    cur.execute(
                        """
                        SELECT id, citation, content, source_url, source_object_key, source_type,
                               last_scraped_at,
                               1 - (embedding <=> %s::vector) AS cosine_sim
                        FROM knowledge_chunks
                        WHERE is_current = true
                          AND (%s::text[] IS NULL OR source_type = ANY(%s))
                        ORDER BY embedding <=> %s::vector
                        LIMIT %s
                        """,
                        (embedding, source_types, source_types, embedding, limit),
                    )
                    rows = cur.fetchall()
                    cur.close()
                    return list(rows)

        return await asyncio.to_thread(_search)

    async def historical_search(
        self,
        *,
        embedding: list[float],
        source_types: list[str] | None = None,
        limit: int = 3,
    ) -> list[VectorHit]:
        """Semantic-only search over SUPERSEDED chunks (is_current = false).

        Mirrors :meth:`semantic_search`'s connection/txn/probes idiom but scopes
        the pool to non-current law and selects ``superseded_by`` so the caller
        can surface the supersession lineage. This is the historical pool
        (Task B2): callers down-weight and append these below current law rather
        than citing them as current.
        """

        def _search() -> list[dict]:
            with get_pg_conn() as conn:
                # SET LOCAL only applies inside an explicit transaction; on a pooled
                # connection a bare SET LOCAL outside a transaction silently no-ops. The
                # psycopg2 connection context manager opens/commits one transaction, so we
                # scope the probes tuning and the vector SELECT together here.
                with conn:
                    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                    cur.execute("SET LOCAL ivfflat.probes = %s", (settings.IVFFLAT_PROBES,))
                    cur.execute(
                        """
                        SELECT id, citation, content, source_url, source_object_key, source_type,
                               last_scraped_at, superseded_by,
                               1 - (embedding <=> %s::vector) AS cosine_sim
                        FROM knowledge_chunks
                        WHERE is_current = false
                          AND (%s::text[] IS NULL OR source_type = ANY(%s))
                        ORDER BY embedding <=> %s::vector
                        LIMIT %s
                        """,
                        (embedding, source_types, source_types, embedding, limit),
                    )
                    rows = cur.fetchall()
                    cur.close()
                    return list(rows)

        return await asyncio.to_thread(_search)

    async def text_search(
        self,
        *,
        query: str,
        source_types: list[str] | None = None,
        limit: int = 40,
    ) -> list[VectorHit]:
        def _search() -> list[dict]:
            with get_pg_conn() as conn:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute(
                    """
                    SELECT id, citation, content, source_url, source_object_key, source_type,
                           last_scraped_at,
                           ts_rank(to_tsvector('english', content), plainto_tsquery('english', %s)) AS text_rank
                    FROM knowledge_chunks
                    WHERE is_current = true
                      AND to_tsvector('english', content) @@ plainto_tsquery('english', %s)
                      AND (%s::text[] IS NULL OR source_type = ANY(%s))
                    ORDER BY text_rank DESC
                    LIMIT %s
                    """,
                    (query, query, source_types, source_types, limit),
                )
                rows = cur.fetchall()
                cur.close()
                return list(rows)

        return await asyncio.to_thread(_search)

    async def firm_search(
        self,
        *,
        embedding: list[float],
        client_id: str,
        limit: int = 4,
    ) -> list[VectorHit]:
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
                        (embedding, client_id, embedding, limit),
                    )
                    rows = cur.fetchall()
                    cur.close()
                    return list(rows)

        rows = await asyncio.to_thread(_search)
        # Map the firm_knowledge row shape into the provider-agnostic VectorHit
        # dict. The raw cosine similarity is carried as `score`; the caller
        # (research._firm_knowledge_search) applies the FIRM_CHUNK_WEIGHT
        # multiplier so the weighting policy stays in the service layer.
        return [
            {
                "id": str(r["id"]),
                "citation": f"Firm knowledge: {r['file_name']}",
                "content": r["content"],
                "source_url": "",
                "source_object_key": None,
                "last_scraped_at": None,  # not a scraped source - no freshness concept applies
                "score": float(r["sim"]),
            }
            for r in rows
        ]

    async def engagement_search(
        self,
        *,
        embedding: list[float],
        client_id: str,
        client_ref: str,
        limit: int = 4,
    ) -> list[VectorHit]:
        """Semantic search over prior engagement memos for ONE client engagement
        (Task C4). Mirrors :meth:`firm_search`'s txn/probes idiom but scopes the
        pool to a single ``(client_id, client_ref)`` so a memo is only ever
        surfaced back into the same engagement it came from. The caller
        (``research._engagement_search``) applies ENGAGEMENT_CHUNK_WEIGHT so the
        weighting policy stays in the service layer.
        """

        def _search() -> list[dict]:
            with get_pg_conn() as conn:
                # SET LOCAL needs an explicit transaction on the pooled connection
                # (Task A5); the psycopg2 connection context manager provides one.
                with conn:
                    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                    cur.execute("SET LOCAL ivfflat.probes = %s", (settings.IVFFLAT_PROBES,))
                    cur.execute(
                        """
                        SELECT id, title, content,
                               1 - (embedding <=> %s::vector) AS sim
                        FROM engagement_context
                        WHERE client_id = %s AND client_ref = %s AND embedding IS NOT NULL
                        ORDER BY embedding <=> %s::vector
                        LIMIT %s
                        """,
                        (embedding, client_id, client_ref, embedding, limit),
                    )
                    rows = cur.fetchall()
                    cur.close()
                    return list(rows)

        rows = await asyncio.to_thread(_search)
        return [
            {
                "id": str(r["id"]),
                "citation": f"Engagement memo: {r['title']}",
                "content": r["content"],
                "source_url": "",
                "source_object_key": None,
                "last_scraped_at": None,  # not a scraped source - no freshness concept applies
                "score": float(r["sim"]),
            }
            for r in rows
        ]
