"""Module 4: regulatory monitor. Polls public AU regulator feeds and records new
items in regulatory_alerts. Client-communication drafting is attached when the
Anthropic API is available; alert detection works without it."""
import asyncio
import xml.etree.ElementTree as ET

import httpx
import psycopg2

from taxflow.config import settings

FEEDS = [
    # (feed_url, source, alert_type)
    ("https://www.austlii.edu.au/cgi-bin/rssdisp.cgi?db=/au/cases/cth/FCA&count=20", "fca", "new_ruling"),
    ("https://www.austlii.edu.au/cgi-bin/rssdisp.cgi?db=/au/cases/cth/AATA&count=20", "aata", "new_ruling"),
]

USER_AGENT = "TaxFlowAI/1.0 (regulatory monitor; contact: crewcircle@zohomail.com.au)"


async def check_feeds() -> int:
    """Fetch all feeds, insert unseen items into regulatory_alerts. Returns new-alert count."""
    items: list[dict] = []
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True) as client:
        for feed_url, source, alert_type in FEEDS:
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

    def _insert() -> int:
        conn = psycopg2.connect(settings.DATABASE_URL)
        cur = conn.cursor()
        inserted = 0
        for item in items:
            cur.execute("SELECT 1 FROM regulatory_alerts WHERE url = %s", (item["url"],))
            if cur.fetchone():
                continue
            cur.execute(
                "INSERT INTO regulatory_alerts (source, alert_type, title, url) VALUES (%s, %s, %s, %s)",
                (item["source"], item["alert_type"], item["title"], item["url"]),
            )
            inserted += 1
        conn.commit()
        cur.close()
        conn.close()
        return inserted

    return await asyncio.to_thread(_insert)


def scheduled_monitor() -> None:
    """Sync wrapper for APScheduler."""
    count = asyncio.run(check_feeds())
    print(f"regulatory monitor: {count} new alerts")
