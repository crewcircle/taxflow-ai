from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()


def _register_jobs() -> None:
    from taxflow.services.knowledge.ingest import run_all
    from taxflow.services.regulatory_monitor import check_feeds

    # Daily knowledge base delta scrape, 2am Sydney time (UTC+10/11 -> use 16:00 UTC)
    scheduler.add_job(run_all, "cron", hour=16, minute=0, id="kb_ingestion", replace_existing=True)
    # Regulatory monitor every 2 hours
    scheduler.add_job(check_feeds, "interval", hours=2, id="regulatory_monitor", replace_existing=True)


def start_scheduler() -> None:
    if not scheduler.running:
        _register_jobs()
        scheduler.start()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)


def is_running() -> bool:
    return scheduler.running
