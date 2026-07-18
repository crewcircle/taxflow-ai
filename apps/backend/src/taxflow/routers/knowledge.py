from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse

from taxflow.db import get_db
from taxflow.middleware.auth import get_current_client
from taxflow.services.storage.r2 import get_source_pdf_url

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/source/{object_key}")
async def get_source_document(object_key: str, _client=Depends(get_current_client)):
    """Redirect to a signed URL for a stored original source PDF."""
    url = get_source_pdf_url(object_key)
    if not url:
        raise HTTPException(status_code=404, detail="Source document not available")
    return RedirectResponse(url)


@router.get("/graph")
async def get_knowledge_graph(_client=Depends(get_current_client), db=Depends(get_db)):
    """Metadata-only view of the knowledge base for the graph/table explorer -
    never returns chunk `content`, just enough per citation to browse,
    categorise, and audit freshness. Returns a flat `documents` list (every
    groupable attribute a document has - topic(s), jurisdiction, source_type,
    is_current, cited_count) so the frontend can switch between grouping
    views (by topic, by jurisdiction, by source type, by currency status)
    without another round trip, plus a topic-hub `nodes`/`edges` shape for
    the graph view.
    """
    import asyncio

    rows = await asyncio.to_thread(db.knowledge_ingest.graph_metadata)

    documents = []
    topic_counts: dict[str, int] = {}
    edges = []
    for row in rows:
        topics = row["topics"] or ["Uncategorised"]
        documents.append(
            {
                "id": row["citation"],
                "type": "document",
                "title": row["title"],
                "source_type": row["source_type"],
                "jurisdiction": row["jurisdiction"] or "Federal",
                "source_url": row["source_url"],
                "chunk_count": row["chunk_count"],
                "is_current": row["is_current"],
                "last_scraped_at": row["last_scraped_at"].isoformat() if row["last_scraped_at"] else None,
                "topics": topics,
                "cited_count": row["cited_count"],
            }
        )
        for topic in topics:
            topic_counts[topic] = topic_counts.get(topic, 0) + 1
            edges.append({"source": row["citation"], "target": topic})

    topic_nodes = [
        {"id": topic, "type": "topic", "document_count": count} for topic, count in topic_counts.items()
    ]

    return {"documents": documents, "nodes": documents + topic_nodes, "edges": edges}
