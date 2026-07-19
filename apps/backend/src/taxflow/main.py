from contextlib import asynccontextmanager

from fastapi import FastAPI

from taxflow import providers
from taxflow.config import settings
from taxflow.routers import (
    health,
    auth,
    contact,
    query,
    documents,
    ato_response,
    firm_clients,
    firm_knowledge,
    knowledge,
    regulatory_alerts,
    webhooks,
    settings as settings_router,
)
from taxflow.scheduler import start_scheduler, stop_scheduler


async def _assert_embedding_dimension() -> None:
    """Validate that the live embedder's real output length matches config.

    DB columns (``knowledge_chunks.embedding`` / ``firm_knowledge.embedding``)
    are ``vector(EMBEDDING_DIMENSION)``, so a provider/model whose true vector
    length differs would silently break inserts and similarity search. Probe the
    embedder on a short string and fail fast if reality disagrees with config.
    """
    probe = "healthcheck"
    embedding = await providers.get_embedder().embed(probe)
    actual = len(embedding)
    if actual != settings.EMBEDDING_DIMENSION:
        raise RuntimeError(
            "Embedding dimension mismatch: the configured embedder returned "
            f"{actual}-dim vectors but EMBEDDING_DIMENSION is "
            f"{settings.EMBEDDING_DIMENSION}. The pgvector columns are "
            f"vector({settings.EMBEDDING_DIMENSION}); changing provider/model "
            "requires a migration + full re-embed."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.EMBEDDING_DIM_GUARD_ENABLED:
        await _assert_embedding_dimension()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="TaxFlow AI API", version="0.1.0", lifespan=lifespan)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(contact.router)
app.include_router(query.router)
app.include_router(documents.router)
app.include_router(ato_response.router)
app.include_router(firm_clients.router)
app.include_router(firm_knowledge.router)
app.include_router(knowledge.router)
app.include_router(regulatory_alerts.router)
app.include_router(webhooks.router)
app.include_router(settings_router.router)
