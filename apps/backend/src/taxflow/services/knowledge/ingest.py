"""Knowledge base ingestion entrypoints - called by the scheduler and by CLI runs.

CLI usage (full run):    uv run python -m taxflow.services.knowledge.ingest
CLI smoke test:          uv run python -m taxflow.services.knowledge.ingest --limit 2
"""
import argparse
import asyncio

from taxflow.services.knowledge.scrapers.ato_rulings import ATORulingsScraper
from taxflow.services.knowledge.scrapers.austlii import AustLIIScraper
from taxflow.services.knowledge.scrapers.legislation import LegislationScraper
from taxflow.services.knowledge.scrapers.state_revenue import STATES, StateRevenueScraper

# (name, zero-arg factory) - state scrapers all share one class parameterised by
# a StateConfig (see scrapers/state_revenue.py), so they can't be listed as bare
# classes the way the single-jurisdiction scrapers can.
ALL_SCRAPERS = [
    ("ATORulingsScraper", ATORulingsScraper),
    ("LegislationScraper", LegislationScraper),
    ("AustLIIScraper", AustLIIScraper),
] + [
    (f"StateRevenueScraper[{config.jurisdiction}]", lambda c=config: StateRevenueScraper(c))
    for config in STATES
]


async def run_all(limit: int | None = None) -> dict[str, int]:
    results: dict[str, int] = {}
    processed_any = False
    for name, factory in ALL_SCRAPERS:
        scraper = factory()
        try:
            print(f"Running {name}...")
            count = await scraper.run_delta(limit=limit)
            results[name] = count
            if count > 0:
                processed_any = True
            print(f"  {count} documents processed")
        except Exception as e:  # noqa: BLE001
            print(f"  {name} failed: {e}")
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
            print(f"  knowledge_version bumped to {new_version}; answer cache invalidated")
        except Exception as e:  # noqa: BLE001 - a bump failure must not fail the ingest
            print(f"  knowledge_version bump failed: {e}")

    return results


def scheduled_ingestion() -> None:
    """Sync wrapper for APScheduler."""
    asyncio.run(run_all())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Max documents per scraper")
    args = parser.parse_args()
    print(asyncio.run(run_all(limit=args.limit)))
