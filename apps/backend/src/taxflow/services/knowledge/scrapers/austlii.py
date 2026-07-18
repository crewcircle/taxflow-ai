import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

from taxflow.services.knowledge.scraper_base import ScraperBase

# Number of RSS items to request per feed for a KB scrape (deeper backfill than
# the regulatory monitor's shallow poll).
FEED_ITEM_COUNT = 50


class AustLIIScraper(ScraperBase):
    source_name = "austlii"

    async def fetch_document_list(self) -> list[dict]:
        # Imported lazily: the canonical feed set lives in the adapters package,
        # which imports this scraper class into SCRAPER_REGISTRY. Importing it at
        # module top would create a circular import.
        from taxflow.adapters.scrapers import AUSTLII_FEEDS, austlii_feed_url

        documents: list[dict] = []
        for feed in AUSTLII_FEEDS:
            feed_url = austlii_feed_url(feed["db"], FEED_ITEM_COUNT)
            try:
                response = await self._get(feed_url)
                root = ET.fromstring(response.text)
            except Exception as e:  # noqa: BLE001
                print(f"  feed failed {feed_url}: {e}")
                continue
            for item in root.iter("item"):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                if not title or not link:
                    continue
                documents.append(
                    {
                        "url": link,
                        "title": title,
                        "citation": title[:100],
                        "source_type": "court_decision",
                        "effective_date": None,
                    }
                )
        return documents

    async def fetch_document_content(self, url: str) -> str:
        response = await self._get(url)
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["nav", "header", "footer", "script", "style"]):
            tag.decompose()
        main = soup.find("article") or soup.body or soup
        return main.get_text(separator="\n", strip=True)
