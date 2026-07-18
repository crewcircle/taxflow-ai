import re

from bs4 import BeautifulSoup

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

_VOLUME_HREF = re.compile(
    r"https://www\.legislation\.gov\.au/[^\"'\s]+/text/original/epub/OEBPS/document_(\d+)/document_\d+\.html"
)


class LegislationScraper(ScraperBase):
    """legislation.gov.au's Angular app is server-side rendered (confirmed live:
    a plain GET to /{titleId}/latest/text returns the fully populated page,
    `ng-server-context="ssr"` in the markup), so no headless browser is needed
    here at all - a first attempt at this used Playwright because a plain GET
    against a STALE registerId returned a client-only "could not be loaded"
    error shell, which looked like an SPA-rendering problem but wasn't one.

    A large Act's compiled text isn't on that page either, though: it's split
    across N per-volume EPUB documents (ITAA 1936 has 7, ITAA 1997 has 12),
    each linked from the page as a plain static XHTML file. This scraper reads
    those links off the page and concatenates every volume in order - reading
    only the first volume (an earlier version of this scraper effectively did,
    via a single-frame grab) silently dropped everything after it; for ITAA
    1936 that cut off Division 6 (sections 95-102) entirely, which lives in
    volume 2.
    """

    source_name = "legislation"

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

    def _extract_text(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["nav", "header", "footer", "script", "style", "aside"]):
            tag.decompose()
        main = soup.find("main") or soup.find("article") or soup.body or soup
        return main.get_text(separator="\n", strip=True)

    async def fetch_document_content(self, url: str) -> str:
        response = await self._get(url)
        html = response.text
        if "could not be loaded" in html:
            return ""  # stale/invalid titleId - nothing to scrape

        # Dedup by volume number and order 1..N (the page can link the same
        # volume more than once, e.g. from both the TOC and a "downloads" list).
        seen: dict[int, str] = {}
        for match in _VOLUME_HREF.finditer(html):
            seen.setdefault(int(match.group(1)), match.group(0))
        volume_urls = [seen[n] for n in sorted(seen)]

        if not volume_urls:
            # Small Acts may render their full text directly on this page with
            # no per-volume split - fall back to whatever's here.
            text = self._extract_text(html)
            return text if len(text) >= 3000 else ""

        parts = []
        for vol_url in volume_urls:
            vol_response = await self._get(vol_url)
            parts.append(self._extract_text(vol_response.text))
        text = "\n\n".join(parts)
        if len(text) < 3000:
            return ""  # didn't actually get compiled text - skip rather than ingest junk
        return text
