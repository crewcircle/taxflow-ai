from bs4 import BeautifulSoup
from playwright.async_api import Browser, async_playwright

from taxflow.services.knowledge.scraper_base import ScraperBase

# Key AU tax legislation, by titleId on legislation.gov.au. titleId is the
# permanent identifier for an Act (looked up once via the OData Titles API,
# e.g. https://api.prod.legislation.gov.au/v1/titles?$filter=name eq '...'
# and collection eq 'Act') and does NOT change across compilations - unlike
# the registerId/compilationNumber pair, which changes every time the Act is
# amended. The old version of this list hardcoded a registerId snapshot,
# which silently went stale and made every fetch 404 ("requested title could
# not be loaded"). https://www.legislation.gov.au/{titleId}/latest/text
# always resolves to the current compilation regardless of amendments.
ACTS = [
    ("C2004A05138", "Income Tax Assessment Act 1997", "ITAA 1997"),
    ("C1936A00027", "Income Tax Assessment Act 1936", "ITAA 1936"),
    ("C2004A00446", "A New Tax System (Goods and Services Tax) Act 1999", "GST Act"),
    ("C2004A03280", "Fringe Benefits Tax Assessment Act 1986", "FBTAA 1986"),
    ("C2004A04402", "Superannuation Guarantee (Administration) Act 1992", "SGA Act"),
]


class LegislationScraper(ScraperBase):
    """legislation.gov.au is an Angular SPA - the act text is rendered client-side
    from api.prod.legislation.gov.au, whose document-file endpoint doesn't serve
    document bytes publicly (confirmed by direct API testing). A plain httpx GET
    only ever returns the empty SPA shell, so this scraper renders each page with
    a real (headless) browser instead and reads the DOM after it settles.

    The compiled Act text itself isn't in the top-level page: the app fetches an
    EPUB client-side and mounts it in a second frame at a blob: URL (confirmed by
    inspecting page.frames() live), so fetch_document_content reads that frame's
    body text, not the outer page's.

    One Chromium instance is shared across every Act in a run_delta() call
    (opened lazily on first use, closed in aclose()) rather than launched per
    document - launching a browser process is expensive and ingest.py already
    calls aclose() exactly once per scraper instance per run.
    """

    source_name = "legislation"

    def __init__(self) -> None:
        super().__init__()
        self._playwright = None
        self._browser: Browser | None = None

    async def fetch_document_list(self) -> list[dict]:
        return [
            {
                "url": f"https://www.legislation.gov.au/{comp_id}/latest/text",
                "title": title,
                "citation": citation,
                "source_type": "legislation",
                "effective_date": None,
            }
            for comp_id, title, citation in ACTS
        ]

    async def _ensure_browser(self) -> Browser:
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
        return self._browser

    async def fetch_document_content(self, url: str) -> str:
        browser = await self._ensure_browser()
        page = await browser.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=60_000)
            if "could not be loaded" in await page.evaluate("document.body.innerText"):
                return ""  # stale/invalid titleId - nothing to scrape
            # The compiled text loads into a second frame (a blob: URL the app
            # creates client-side from a fetched EPUB) after the outer page's
            # networkidle fires, so poll for that frame to appear.
            epub_frame = None
            for _ in range(30):
                frames = [f for f in page.frames if f.url.startswith("blob:")]
                if frames:
                    epub_frame = frames[0]
                    break
                await page.wait_for_timeout(1000)
            if epub_frame is None:
                return ""
            try:
                await epub_frame.wait_for_function(
                    "document.body.innerText.length > 3000", timeout=20_000
                )
            except Exception:  # noqa: BLE001 - fall through to the length guard below
                pass
            html = await epub_frame.content()
        finally:
            await page.close()

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["nav", "header", "footer", "script", "style", "aside"]):
            tag.decompose()
        main = soup.find("main") or soup.find("article") or soup.body or soup
        text = main.get_text(separator="\n", strip=True)
        if len(text) < 3000:
            return ""  # didn't actually get the compiled text - skip rather than ingest junk
        return text

    async def aclose(self) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()
        await super().aclose()
