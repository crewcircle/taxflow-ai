from contextlib import asynccontextmanager

from fastapi import FastAPI

from taxflow.routers import (
    health,
    auth,
    contact,
    query,
    documents,
    ato_response,
    firm_knowledge,
    regulatory_alerts,
    webhooks,
    settings as settings_router,
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
app.include_router(contact.router)
app.include_router(query.router)
app.include_router(documents.router)
app.include_router(ato_response.router)
app.include_router(firm_knowledge.router)
app.include_router(regulatory_alerts.router)
app.include_router(webhooks.router)
app.include_router(settings_router.router)
