"""One-time seed for ATO rulings/determinations outside ATORulingsScraper's
normal brute-force range (RAG-quality audit follow-up).

ATORulingsScraper.fetch_document_list() only enumerates YEARS = 2018-2026 -
a deliberate bound on brute-force PDF-existence checks (~30 numbers x 3
series x N years, mostly 404s). A document from before 2018 is never
discovered by the normal ingestion run, even though the ATO Legal Database
still serves it at the same predictable PDF URL pattern. This script hand-
seeds a small, individually VERIFIED list of such documents instead - each
URL was fetched directly and confirmed to return a real PDF before being
added here (see the "never guess URLs" lesson in seed_landmark_cases.py).

Run: doppler run --project taxflow --config prd -- \\
     uv run python scripts/seed_pre2018_ato_rulings.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from taxflow.services.knowledge.pipeline import process_document  # noqa: E402
from taxflow.services.knowledge.scrapers.ato_rulings import ATORulingsScraper  # noqa: E402

# Each URL verified live (200, application/pdf) before being added here.
PRE_2018_RULINGS = [
    {
        "url": "https://www.ato.gov.au/law/view/pdf/pbr/td2014-025.pdf",
        "title": "TD 2014/25",
        "citation": "TD 2014/25",
        "source_type": "ato_determination",
    },
]


async def main() -> None:
    scraper = ATORulingsScraper()
    try:
        for ruling in PRE_2018_RULINGS:
            print(f"Fetching: {ruling['citation']}...")
            text = await scraper.fetch_document_content(ruling["url"])
            if not text or len(text) < 500:
                print(f"  SKIPPED - fetch returned too little content ({len(text)} chars)")
                continue
            count = await process_document(
                text,
                {
                    "source_type": ruling["source_type"],
                    "url": ruling["url"],
                    "title": ruling["title"],
                    "citation": ruling["citation"],
                    "effective_date": None,
                    "jurisdiction": None,
                },
                source_object_key=scraper._last_object_key,
            )
            print(f"  ingested {count} chunks")
    finally:
        await scraper.aclose()


if __name__ == "__main__":
    asyncio.run(main())
