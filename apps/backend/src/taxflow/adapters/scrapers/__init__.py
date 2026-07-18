"""Source-scraper adapters and registry.

Holds the single canonical source-scraper registry (``SCRAPER_REGISTRY``,
previously defined in ``services/knowledge/ingest.py``) and the one canonical
AustLII RSS feed list (``AUSTLII_FEEDS``) shared by both the knowledge-base
scraper (``services/knowledge/scrapers/austlii.py``) and the regulatory monitor
(``services/regulatory_monitor.py``), so the feed set lives in exactly one place.

The two callers previously kept separate literal copies that differed only by
the per-request ``count`` query parameter; that count stays a per-caller
argument to ``austlii_feed_url`` while the feed set itself is deduplicated here.
"""

from __future__ import annotations

# --- canonical AustLII feed set ---------------------------------------------
# Defined BEFORE importing the scraper classes below so that ``austlii.py``
# (which imports these names from this package) can complete its import while
# this package is still initialising.
AUSTLII_FEED_URL_TEMPLATE = "https://www.austlii.edu.au/cgi-bin/rssdisp.cgi?db={db}&count={count}"

# Each entry describes one AustLII RSS feed. ``court`` is used by the KB scraper
# for citation context; ``source``/``alert_type`` are used by the regulatory
# monitor when recording alerts. The URL is built per-caller via
# ``austlii_feed_url`` with a caller-specific ``count``.
AUSTLII_FEEDS = [
    {"db": "/au/cases/cth/FCA", "court": "FCA", "source": "fca", "alert_type": "new_ruling"},
    {"db": "/au/cases/cth/AATA", "court": "AATA", "source": "aata", "alert_type": "new_ruling"},
]


def austlii_feed_url(db: str, count: int) -> str:
    """Build an AustLII RSS feed URL for a feed ``db`` path and item ``count``."""
    return AUSTLII_FEED_URL_TEMPLATE.format(db=db, count=count)


from taxflow.services.knowledge.scrapers.ato_rulings import ATORulingsScraper  # noqa: E402
from taxflow.services.knowledge.scrapers.austlii import AustLIIScraper  # noqa: E402
from taxflow.services.knowledge.scrapers.legislation import LegislationScraper  # noqa: E402
from taxflow.services.knowledge.scrapers.state_revenue import (  # noqa: E402
    STATES,
    StateRevenueScraper,
)

# The source-scraper registry consumed via ``providers.get_scraper_registry()``.
# Each entry is a ``(name, factory)`` tuple where ``factory`` is a zero-arg
# callable returning a fresh scraper. Most scrapers are single-jurisdiction bare
# classes; the state revenue offices all share one ``StateRevenueScraper`` class
# parameterised by a ``StateConfig`` (see ``scrapers/state_revenue.py``), so each
# state gets its own factory that closes over its config.
SCRAPER_REGISTRY = [
    ("ATORulingsScraper", ATORulingsScraper),
    ("LegislationScraper", LegislationScraper),
    ("AustLIIScraper", AustLIIScraper),
] + [
    (f"StateRevenueScraper[{config.jurisdiction}]", lambda c=config: StateRevenueScraper(c))
    for config in STATES
]

__all__ = [
    "AUSTLII_FEEDS",
    "AUSTLII_FEED_URL_TEMPLATE",
    "austlii_feed_url",
    "SCRAPER_REGISTRY",
    "ATORulingsScraper",
    "AustLIIScraper",
    "LegislationScraper",
    "StateRevenueScraper",
    "STATES",
]
