import io

import pdfplumber

from taxflow.services.knowledge.scraper_base import ScraperBase

# The ATO Legal Database serves ruling PDFs at predictable URLs. The HTML index
# pages sit behind Akamai bot filtering, but the PDF documents themselves are
# directly fetchable. Series: TR (taxation rulings) and TD (taxation
# determinations) under /pbr/, PCG (practical compliance guidelines) under /cog/.
SERIES = [
    ("tr", "pbr", "ato_ruling", "TR"),
    ("td", "pbr", "ato_determination", "TD"),
    ("pcg", "cog", "ato_guide", "PCG"),
]
YEARS = range(2026, 2017, -1)  # newest first
MAX_NUMBER_PER_YEAR = 30

# ATO's Akamai config rejects non-browser user agents even for public documents.
# We identify ourselves via X-Contact instead and keep the polite rate limit.
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class ATORulingsScraper(ScraperBase):
    source_name = "ato_rulings"

    def __init__(self) -> None:
        super().__init__()
        self._client.headers["User-Agent"] = BROWSER_UA
        self._client.headers["X-Contact"] = "crewcircle@zohomail.com.au"

    async def fetch_document_list(self) -> list[dict]:
        documents = []
        for prefix, directory, source_type, series_label in SERIES:
            for year in YEARS:
                for number in range(1, MAX_NUMBER_PER_YEAR + 1):
                    documents.append(
                        {
                            "url": f"https://www.ato.gov.au/law/view/pdf/{directory}/{prefix}{year}-{number:03d}.pdf",
                            "title": f"{series_label} {year}/{number}",
                            "citation": f"{series_label} {year}/{number}",
                            "source_type": source_type,
                            "effective_date": None,
                        }
                    )
        return documents

    async def fetch_document_content(self, url: str) -> str:
        response = await self._get(url)
        if response.status_code != 200 or "pdf" not in response.headers.get("content-type", ""):
            return ""  # ruling number doesn't exist - run_delta skips empty content
        with pdfplumber.open(io.BytesIO(response.content)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
