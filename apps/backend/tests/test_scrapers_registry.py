"""Task B8: source-scraper registry + AustLII feed dedupe.

Asserts the canonical ``SCRAPER_REGISTRY`` lists every scraper (the three
single-jurisdiction scrapers plus one parameterised ``StateRevenueScraper`` per
state), each conforms to the ``SourceScraperPort`` Protocol, and that the KB
scraper (``scrapers/austlii.py``) and the regulatory monitor
(``services/regulatory_monitor.py``) reference the *same* canonical feed
constant rather than duplicating the feed list.
"""

from __future__ import annotations

from taxflow.adapters.scrapers import (
    STATES,
    SCRAPER_REGISTRY,
    AUSTLII_FEEDS,
    ATORulingsScraper,
    AustLIIScraper,
    LegislationScraper,
    StateRevenueScraper,
    austlii_feed_url,
)
from taxflow.ports.scrapers import SourceScraperPort

REQUIRED_METHODS = ("fetch_document_list", "fetch_document_content", "run_delta", "aclose")


def test_registry_lists_all_scrapers():
    names = [name for name, _factory in SCRAPER_REGISTRY]
    # The three single-jurisdiction scrapers, in order, come first.
    assert names[:3] == ["ATORulingsScraper", "LegislationScraper", "AustLIIScraper"]
    # Then one StateRevenueScraper entry per configured state.
    assert len(SCRAPER_REGISTRY) == 3 + len(STATES)
    for config in STATES:
        assert f"StateRevenueScraper[{config.jurisdiction}]" in names


def test_each_scraper_conforms_to_source_scraper_port():
    import asyncio

    for _name, factory in SCRAPER_REGISTRY:
        instance = factory()
        try:
            # runtime_checkable Protocol structural check
            assert isinstance(instance, SourceScraperPort)
            # explicit attr/method presence for clarity
            assert isinstance(instance.source_name, str) and instance.source_name
            for method in REQUIRED_METHODS:
                assert callable(getattr(instance, method))
        finally:
            asyncio.run(instance.aclose())


def test_austlii_and_regulatory_monitor_share_the_same_feed_constant():
    import taxflow.services.regulatory_monitor as regmon

    # The regulatory monitor imports the canonical constant, not a private copy.
    assert regmon.AUSTLII_FEEDS is AUSTLII_FEEDS

    # The KB scraper module no longer defines a duplicate literal feed list.
    import taxflow.services.knowledge.scrapers.austlii as austlii

    assert not hasattr(austlii, "RSS_FEEDS")


def test_feed_url_builder_applies_per_caller_count():
    url = austlii_feed_url("/au/cases/cth/FCA", 20)
    assert "db=/au/cases/cth/FCA" in url
    assert "count=20" in url
    assert austlii_feed_url("/au/cases/cth/FCA", 50) != url
