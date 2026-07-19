"""Re-chunk / re-embed backfill (Workstream C, Task C4).

Re-ingests every already-ingested knowledge source through the hierarchical
chunker. Uses the re-scrape + DB-driven-metadata contract:

- ``list_ingested_sources()`` (a KnowledgeIngestRepo port method) returns one
  row per distinct ``source_url`` with exactly the fields ``process_document``
  reads from ``metadata`` — no object-storage read path is needed.
- A deterministic scraper resolver maps a ``(source_url, source_type)`` to a
  scraper in ``SCRAPER_REGISTRY`` by URL host / source_type. Unresolved sources
  are skipped and logged (never silently dropped).
- For each source: resolve scraper -> ``fetch_document_content(url)`` (fresh
  text) -> ``delete_by_source_url(url)`` -> ``process_document(text, metadata,
  source_object_key=...)`` with ``HIERARCHICAL_CHUNKING_ENABLED`` on.

Delete-before-reinsert is required: hierarchical chunking produces a different
chunk count, so a plain ``ON CONFLICT (source_url, chunk_index)`` re-upsert would
leave stale high-index flat rows behind.

This is an OPERATIONAL, gated script (real Anthropic/OpenAI calls via the
pipeline) — it is never run at deploy. Supports ``--limit`` / ``--dry-run`` /
``--source``.

Run: doppler run --project taxflow --config prd -- \\
     uv run python scripts/rechunk_backfill.py --limit 5 --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from taxflow.config import settings  # noqa: E402
from taxflow.providers import get_relational_data, get_scraper_registry  # noqa: E402
from taxflow.services.knowledge.pipeline import process_document  # noqa: E402


# --- scraper resolver --------------------------------------------------------
# Maps a source to the registry NAME of the scraper that owns it. The registry
# entries are ``(name, factory)`` tuples and SourceScraperPort has no owns_url(),
# so this deterministic host/source_type resolver lives here (and is unit-tested
# for representative URLs).

# Host substrings -> registry scraper name. Checked before source_type so a URL
# always wins when its host is recognised.
_HOST_RULES: list[tuple[str, str]] = [
    ("ato.gov.au", "ATORulingsScraper"),
    ("legislation.gov.au", "LegislationScraper"),
    ("austlii.edu.au", "AustLIIScraper"),
    # State revenue offices all share one StateRevenueScraper class (one factory
    # per state in the registry); resolve to the matching state factory by host.
    ("revenue.nsw.gov.au", "StateRevenueScraper[NSW]"),
    ("sro.vic.gov.au", "StateRevenueScraper[VIC]"),
    ("wa.gov.au", "StateRevenueScraper[WA]"),
    ("sro.tas.gov.au", "StateRevenueScraper[TAS]"),
    ("revenue.act.gov.au", "StateRevenueScraper[ACT]"),
    ("treasury.nt.gov.au", "StateRevenueScraper[NT]"),
]

# Fallback: source_type -> registry scraper name (used when the host is not
# recognised but the source_type is). State sources fall back to NSW as a
# representative state scraper only if nothing more specific matched.
_SOURCE_TYPE_RULES: dict[str, str] = {
    "ato_ruling": "ATORulingsScraper",
    "ato_determination": "ATORulingsScraper",
    "ato_guide": "ATORulingsScraper",
    "legislation": "LegislationScraper",
    "court_decision": "AustLIIScraper",
}


def resolve_scraper_name(source_url: str | None, source_type: str | None) -> str | None:
    """Return the registry scraper NAME for a source, or None if unresolved.

    Deterministic: host match first (most specific), then source_type fallback.
    """
    host = (urlparse(source_url).netloc or "").lower() if source_url else ""
    for needle, name in _HOST_RULES:
        if needle in host:
            return name
    if source_type and source_type in _SOURCE_TYPE_RULES:
        return _SOURCE_TYPE_RULES[source_type]
    return None


def resolve_scraper(source_url: str | None, source_type: str | None, registry):
    """Resolve to a fresh scraper INSTANCE from ``registry`` (a list of
    ``(name, factory)`` tuples), or None if unresolved / not registered."""
    name = resolve_scraper_name(source_url, source_type)
    if name is None:
        return None
    for reg_name, factory in registry:
        if reg_name == name:
            return factory()
    return None


def _metadata_from_row(row: dict) -> dict:
    """Rebuild the ``process_document`` metadata dict from a DB source row.

    ``list_ingested_sources`` returns ``source_url`` which the pipeline reads as
    ``url``; the rest of the keys map straight through.
    """
    return {
        "url": row["source_url"],
        "source_type": row.get("source_type"),
        "title": row.get("title"),
        "citation": row.get("citation"),
        "effective_date": row.get("effective_date"),
        "jurisdiction": row.get("jurisdiction"),
    }


async def backfill_source(row: dict, registry, repo, *, dry_run: bool) -> str:
    """Re-ingest one source. Returns a short status string for logging."""
    source_url = row["source_url"]
    scraper = resolve_scraper(source_url, row.get("source_type"), registry)
    if scraper is None:
        return f"SKIP (no scraper): {source_url}"

    try:
        text = await scraper.fetch_document_content(source_url)
    finally:
        # Scrapers hold an httpx client; close it best-effort.
        aclose = getattr(scraper, "aclose", None)
        if aclose is not None:
            await aclose()

    if not text or len(text) < 200:
        return f"SKIP (empty/short content): {source_url}"

    if dry_run:
        return f"DRY-RUN would re-ingest: {source_url} ({len(text)} chars)"

    deleted = await asyncio.to_thread(repo.delete_by_source_url, source_url)
    metadata = _metadata_from_row(row)
    count = await process_document(
        text, metadata, source_object_key=row.get("source_object_key")
    )
    return f"OK re-ingested {source_url}: -{deleted} old, +{count} new chunks"


async def run_backfill(*, limit: int | None, dry_run: bool, source: str | None) -> None:
    # The whole backfill runs with hierarchical chunking ON so the re-ingest
    # produces the new hierarchical chunks regardless of the deploy default.
    settings.HIERARCHICAL_CHUNKING_ENABLED = True

    repo = get_relational_data().knowledge_ingest
    registry = get_scraper_registry()
    sources = await asyncio.to_thread(repo.list_ingested_sources)

    if source:
        sources = [s for s in sources if s["source_url"] == source]
    if limit:
        sources = sources[:limit]

    print(f"Re-chunk backfill: {len(sources)} source(s), dry_run={dry_run}")
    for row in sources:
        try:
            status = await backfill_source(row, registry, repo, dry_run=dry_run)
        except Exception as e:  # noqa: BLE001 - one bad source must not kill the run
            status = f"ERROR {row.get('source_url')}: {e}"
        print(f"  {status}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Re-chunk / re-embed backfill (Task C4).")
    parser.add_argument("--limit", type=int, default=None, help="Max sources to process.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve + fetch but do NOT delete or re-ingest.",
    )
    parser.add_argument(
        "--source", type=str, default=None, help="Only process this exact source_url."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    asyncio.run(run_backfill(limit=args.limit, dry_run=args.dry_run, source=args.source))


if __name__ == "__main__":
    main()
