import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

from taxflow.services.knowledge.scraper_base import ScraperBase

RSS_FEEDS = [
    ("https://www.austlii.edu.au/cgi-bin/rssdisp.cgi?db=/au/cases/cth/FCA&count=50", "FCA"),
    ("https://www.austlii.edu.au/cgi-bin/rssdisp.cgi?db=/au/cases/cth/AATA&count=50", "AATA"),
]


class AustLIIScraper(ScraperBase):
    source_name = "austlii"

    async def fetch_document_list(self) -> list[dict]:
        documents: list[dict] = []
        for feed_url, court in RSS_FEEDS:
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
