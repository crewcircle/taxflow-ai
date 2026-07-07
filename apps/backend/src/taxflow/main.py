from contextlib import asynccontextmanager

from fastapi import FastAPI

from taxflow.routers import (
    health,
    auth,
    query,
    documents,
    ato_response,
    firm_knowledge,
    webhooks,
)
from taxflow.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="TaxFlow AI API", version="0.1.0", lifespan=lifespan)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(query.router)
app.include_router(documents.router)
app.include_router(ato_response.router)
app.include_router(firm_knowledge.router)
app.include_router(webhooks.router)
