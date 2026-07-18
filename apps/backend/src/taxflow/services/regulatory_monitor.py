"""Module 4: regulatory monitor. Polls public AU regulator feeds and records new
items in regulatory_alerts. Client-communication drafting is attached when the
Anthropic API is available; alert detection works without it."""
import asyncio
import xml.etree.ElementTree as ET

import httpx

from taxflow.adapters.scrapers import AUSTLII_FEEDS, austlii_feed_url
from taxflow.providers import get_relational_data

# Number of RSS items to request per feed for a monitor poll (shallow — we only
# want recently published items, not a deep backfill).
FEED_ITEM_COUNT = 20

USER_AGENT = "TaxFlowAI/1.0 (regulatory monitor; contact: crewcircle@zohomail.com.au)"


async def check_feeds() -> int:
    """Fetch all feeds, insert unseen items into regulatory_alerts. Returns new-alert count."""
    items: list[dict] = []
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True) as client:
        for feed in AUSTLII_FEEDS:
            feed_url = austlii_feed_url(feed["db"], FEED_ITEM_COUNT)
            source, alert_type = feed["source"], feed["alert_type"]
            try:
                response = await client.get(feed_url)
                root = ET.fromstring(response.text)
            except Exception as e:  # noqa: BLE001
                print(f"regulatory monitor: feed failed {feed_url}: {e}")
                continue
            for item in root.iter("item"):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                if title and link:
                    items.append({"source": source, "alert_type": alert_type, "title": title, "url": link})

    if not items:
        return 0

    return await asyncio.to_thread(get_relational_data().regulatory_alerts.insert_unseen, items)


def scheduled_monitor() -> None:
    """Sync wrapper for APScheduler."""
    count = asyncio.run(check_feeds())
    print(f"regulatory monitor: {count} new alerts")
