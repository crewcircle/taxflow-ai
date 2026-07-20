"""Knowledge base ingestion entrypoints - called by the scheduler and by CLI runs.

CLI usage (full run):    uv run python -m taxflow.services.knowledge.ingest
CLI smoke test:          uv run python -m taxflow.services.knowledge.ingest --limit 2
"""
import argparse
import asyncio
import logging

from taxflow import providers

logger = logging.getLogger(__name__)


async def run_all(limit: int | None = None) -> dict[str, int]:
    results: dict[str, int] = {}
    processed_any = False
    for name, factory in providers.get_scraper_registry():
        scraper = factory()
        try:
            logger.info("Running %s...", name)
            count = await scraper.run_delta(limit=limit)
            results[name] = count
            if count > 0:
                processed_any = True
            logger.info("%d documents processed", count)
        except Exception as e:  # noqa: BLE001
            logger.warning("%s failed: %s", name, e, exc_info=True)
            results[name] = -1
        finally:
            await scraper.aclose()

    # Task B3: an ingest that changed the knowledge base bumps the shared
    # knowledge_version token so the per-client answer cache invalidates
    # atomically across BOTH uvicorn workers (the key includes this version, so
    # every worker immediately misses on the old cached answers).
    if processed_any:
        import asyncio as _asyncio

        from taxflow.services.answer_cache import bump_knowledge_version

        try:
            new_version = await _asyncio.to_thread(bump_knowledge_version)
            logger.info("knowledge_version bumped to %s; answer cache invalidated", new_version)
        except Exception as e:  # noqa: BLE001 - a bump failure must not fail the ingest
            logger.warning("knowledge_version bump failed: %s", e, exc_info=True)

    return results


def scheduled_ingestion() -> None:
    """Sync wrapper for APScheduler."""
    asyncio.run(run_all())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Max documents per scraper")
    args = parser.parse_args()
    print(asyncio.run(run_all(limit=args.limit)))
