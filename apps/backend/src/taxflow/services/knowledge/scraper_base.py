import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone

import httpx
import psycopg2

from taxflow.config import settings
from taxflow.services.knowledge.pipeline import process_document

USER_AGENT = "TaxFlowAI/1.0 (research purposes; contact: crewcircle@zohomail.com.au)"


class ScraperBase(ABC):
    """Base for all knowledge-base scrapers. Subclasses list documents and fetch content;
    run_delta() handles staleness checks and hands text to the ingestion pipeline."""

    request_interval_seconds = 2.0

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=30,
            follow_redirects=True,
        )
        self._last_request = 0.0

    async def _get(self, url: str) -> httpx.Response:
        # Rate limit: 1 request per request_interval_seconds, retry on 429/5xx
        now = asyncio.get_event_loop().time()
        wait = self._last_request + self.request_interval_seconds - now
        if wait > 0:
            await asyncio.sleep(wait)

        for attempt in range(3):
            self._last_request = asyncio.get_event_loop().time()
            response = await self._client.get(url)
            if response.status_code < 429:
                return response
            await asyncio.sleep(2**attempt * 2)
        response.raise_for_status()
        return response

    @abstractmethod
    async def fetch_document_list(self) -> list[dict]:
        """Return [{url, title, citation, source_type, effective_date}]"""

    @abstractmethod
    async def fetch_document_content(self, url: str) -> str:
        """Return full text of one document."""

    def _stale_urls(self, urls: list[str]) -> set[str]:
        """URLs not scraped in the last 24h (or never scraped)."""
        if not urls:
            return set()
        conn = psycopg2.connect(settings.DATABASE_URL)
        cur = conn.cursor()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        cur.execute(
            "SELECT DISTINCT source_url FROM knowledge_chunks WHERE source_url = ANY(%s) AND last_scraped_at > %s",
            (urls, cutoff),
        )
        fresh = {row[0] for row in cur.fetchall()}
        cur.close()
        conn.close()
        return set(urls) - fresh

    async def run_delta(self, limit: int | None = None) -> int:
        documents = await self.fetch_document_list()
        stale = self._stale_urls([d["url"] for d in documents])
        to_process = [d for d in documents if d["url"] in stale]
        if limit:
            to_process = to_process[:limit]

        processed = 0
        for doc in to_process:
            try:
                text = await self.fetch_document_content(doc["url"])
                if not text or len(text) < 200:
                    continue
                object_key = getattr(self, "_last_object_key", None)
                await process_document(text, doc, source_object_key=object_key)
                processed += 1
            except Exception as e:  # noqa: BLE001 - one bad document must not kill the run
                print(f"  skip {doc['url']}: {e}")
        return processed

    async def aclose(self) -> None:
        await self._client.aclose()
