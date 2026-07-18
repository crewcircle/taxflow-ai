"""Port Protocol for vector + hybrid (semantic + full-text) search.

The pgvector/Postgres-specific SQL (``<=>`` cosine, ``ivfflat.probes``,
``to_tsvector``/``ts_rank``) lives in the concrete adapter. Callers get back
plain :class:`VectorHit` dicts; the RRF merge, source-type boost, firm weighting
and re-rank logic stay in the retrieval service (provider-agnostic).
"""

from __future__ import annotations

from typing import Protocol, TypedDict, runtime_checkable


class VectorHit(TypedDict, total=False):
    id: str
    citation: str
    content: str
    source_url: str | None
    source_object_key: str | None
    source_type: str | None
    last_scraped_at: object  # datetime | None; kept loose to match row shapes
    score: float


@runtime_checkable
class VectorStorePort(Protocol):
    async def semantic_search(
        self,
        *,
        embedding: list[float],
        source_types: list[str] | None = None,
        limit: int = 40,
    ) -> list[VectorHit]: ...

    async def text_search(
        self,
        *,
        query: str,
        source_types: list[str] | None = None,
        limit: int = 40,
    ) -> list[VectorHit]: ...

    async def firm_search(
        self,
        *,
        embedding: list[float],
        client_id: str,
        limit: int = 4,
    ) -> list[VectorHit]: ...
