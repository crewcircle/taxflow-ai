from bs4 import BeautifulSoup

from taxflow.services.knowledge.scraper_base import ScraperBase

# Key AU tax legislation, by current compilation ID on legislation.gov.au
ACTS = [
    ("C2024C00329", "Income Tax Assessment Act 1997", "ITAA 1997"),
    ("C2024C00272", "Income Tax Assessment Act 1936", "ITAA 1936"),
    ("C2023C00321", "A New Tax System (Goods and Services Tax) Act 1999", "GST Act"),
    ("C2015C00308", "Fringe Benefits Tax Assessment Act 1986", "FBTAA 1986"),
    ("C2023C00186", "Superannuation Guarantee (Administration) Act 1992", "SGA Act"),
]


class LegislationScraper(ScraperBase):
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

    async def fetch_document_content(self, url: str) -> str:
        # TODO: legislation.gov.au is an Angular SPA; act text is served through the
        # api.prod.legislation.gov.au OData API whose document-file endpoint is not yet
        # mapped. Until then, detect the SPA shell and skip rather than ingest junk.
        response = await self._get(url)
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["nav", "header", "footer", "script", "style", "aside"]):
            tag.decompose()
        main = soup.find("main") or soup.find("article") or soup.body or soup
        text = main.get_text(separator="\n", strip=True)
        if "Explore the Federal Register of Legislation" in text or len(text) < 3000:
            return ""  # SPA shell, not act text
        return text
