"""One-time seed for landmark AU tax case law, reusing the existing AustLII
scraper + ingestion pipeline unmodified (Fix 3 of the RAG-quality audit).

AustLIIScraper is RSS-feed-based (FCA/AATA "recent decisions" feeds) and has
never surfaced a single case in the corpus, since landmark cases like these
predate any RSS window. This script hand-seeds a small, individually
VERIFIED list of case URLs instead - each one was fetched and its page
title cross-checked against the expected case name before being added here.
Do not add a case to LANDMARK_CASES without that same verification: a citation
repeated across multiple secondary sources (blogs, JADE summaries) for
"FCT v Cooling" as "[1990] FCA 297" turned out to be wrong - that URL is an
unrelated 1990 insolvency matter - which is exactly the failure mode this
script exists to avoid propagating into the knowledge base.

Run: doppler run --project taxflow --config prd -- \\
     uv run python scripts/seed_landmark_cases.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from taxflow.services.knowledge.pipeline import process_document  # noqa: E402
from taxflow.services.knowledge.scrapers.austlii import AustLIIScraper  # noqa: E402

# Each entry verified by fetching the URL and confirming the page's own
# <title> matches the case name before being added - see module docstring.
LANDMARK_CASES = [
    {
        "url": "https://www.austlii.edu.au/cgi-bin/viewdoc/au/cases/cth/HCA/1996/34.html",
        "title": "Federal Commissioner of Taxation v Spotless Services Ltd",
        "citation": "FCT v Spotless Services Ltd [1996] HCA 34",
        "court": "HCA",
    },
]


async def main() -> None:
    scraper = AustLIIScraper()
    try:
        for case in LANDMARK_CASES:
            print(f"Fetching: {case['citation']}...")
            text = await scraper.fetch_document_content(case["url"])
            if not text or len(text) < 500:
                print(f"  SKIPPED - fetch returned too little content ({len(text)} chars)")
                continue
            count = await process_document(
                text,
                {
                    "source_type": "court_decision",
                    "url": case["url"],
                    "title": case["title"],
                    "citation": case["citation"],
                    "effective_date": None,
                    "jurisdiction": "Commonwealth",
                },
            )
            print(f"  ingested {count} chunks")
    finally:
        await scraper.aclose()


if __name__ == "__main__":
    asyncio.run(main())
