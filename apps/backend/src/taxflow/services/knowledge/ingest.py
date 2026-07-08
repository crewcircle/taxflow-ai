"""Knowledge base ingestion entrypoints - called by the scheduler and by CLI runs.

CLI usage (full run):    uv run python -m taxflow.services.knowledge.ingest
CLI smoke test:          uv run python -m taxflow.services.knowledge.ingest --limit 2
"""
import argparse
import asyncio

from taxflow.services.knowledge.scrapers.ato_rulings import ATORulingsScraper
from taxflow.services.knowledge.scrapers.austlii import AustLIIScraper
from taxflow.services.knowledge.scrapers.legislation import LegislationScraper

ALL_SCRAPERS = [ATORulingsScraper, LegislationScraper, AustLIIScraper]


async def run_all(limit: int | None = None) -> dict[str, int]:
    results: dict[str, int] = {}
    for scraper_cls in ALL_SCRAPERS:
        scraper = scraper_cls()
        try:
            print(f"Running {scraper_cls.__name__}...")
            count = await scraper.run_delta(limit=limit)
            results[scraper_cls.__name__] = count
            print(f"  {count} documents processed")
        except Exception as e:  # noqa: BLE001
            print(f"  {scraper_cls.__name__} failed: {e}")
            results[scraper_cls.__name__] = -1
        finally:
            await scraper.aclose()
    return results


def scheduled_ingestion() -> None:
    """Sync wrapper for APScheduler."""
    asyncio.run(run_all())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Max documents per scraper")
    args = parser.parse_args()
    print(asyncio.run(run_all(limit=args.limit)))
