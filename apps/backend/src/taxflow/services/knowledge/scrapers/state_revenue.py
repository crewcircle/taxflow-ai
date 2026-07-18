import io
import re
from dataclasses import dataclass

import pdfplumber
from bs4 import BeautifulSoup
from docx import Document

from taxflow.services.knowledge.scraper_base import ScraperBase

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


@dataclass
class StateConfig:
    jurisdiction: str
    index_url: str
    link_pattern: re.Pattern  # matches an absolute or site-relative href
    base_url: str  # prefix for site-relative matches
    content_type: str  # "html" | "pdf" | "docx" | "mixed" (dispatch on extension)


# Each state revenue office publishes public rulings/circulars on payroll tax
# and duties/land tax differently - some as individual HTML pages, some as
# direct PDF/DOCX links off one index page. Verified live (curl, no browser
# needed anywhere - every one of these is a plain static/server-rendered
# page) against each site's actual public rulings/circulars index before
# writing this config, rather than guessing URL patterns from memory.
#
# SA and QLD are deliberately NOT included yet: their public listing pages
# don't expose direct ruling links the same way (QLD's /public-rulings/ is a
# WordPress archive landing page without a plain link list; SA's rulings live
# under a different, not-yet-confirmed index structure) - shipping a guessed
# pattern for either risked silently ingesting nothing or the wrong content,
# which this codebase has explicitly chosen not to do (see the earlier
# legislation.gov.au scraper history). Follow-up once their real index is
# found, same pattern as everything below.
STATES = [
    StateConfig(
        jurisdiction="NSW",
        index_url="https://www.revenue.nsw.gov.au/about/legislation-and-rulings/revenue-rulings",
        link_pattern=re.compile(
            r"https://www\.revenue\.nsw\.gov\.au/about/legislation-and-rulings/"
            r"revenue-rulings/rulings/[a-z]+/[a-z0-9-]+"
        ),
        base_url="https://www.revenue.nsw.gov.au",
        content_type="html",
    ),
    StateConfig(
        jurisdiction="VIC",
        index_url="https://www.sro.vic.gov.au/about-us/laws-legal-cases-and-rulings/rulings",
        link_pattern=re.compile(r"/about-us/laws-legal-cases-and-rulings/public-rulings/[a-z0-9-]+"),
        base_url="https://www.sro.vic.gov.au",
        content_type="html",
    ),
    StateConfig(
        jurisdiction="WA",
        index_url=(
            "https://www.wa.gov.au/service/financial-management/taxation-and-duty/"
            "find-payroll-tax-forms-and-publications"
        ),
        link_pattern=re.compile(r"/government/publications/[a-z0-9-]+"),
        base_url="https://www.wa.gov.au",
        content_type="html",
    ),
    StateConfig(
        jurisdiction="TAS",
        index_url="https://www.sro.tas.gov.au/resources/rulings",
        link_pattern=re.compile(r"/Documents/[A-Za-z0-9._-]+\.pdf"),
        base_url="https://www.sro.tas.gov.au",
        content_type="pdf",
    ),
    StateConfig(
        jurisdiction="ACT",
        index_url="https://www.revenue.act.gov.au/publications/circulars",
        link_pattern=re.compile(
            r"https://www\.revenue\.act\.gov\.au/__data/assets/pdf_file/\d+/\d+/[A-Za-z0-9._-]+\.pdf"
        ),
        base_url="https://www.revenue.act.gov.au",
        content_type="pdf",
    ),
    StateConfig(
        jurisdiction="NT",
        index_url="https://treasury.nt.gov.au/dtf/territory-revenue-office/publications",
        link_pattern=re.compile(r"https://treasury\.nt\.gov\.au/[A-Za-z0-9/_.-]+\.(?:pdf|docx)"),
        base_url="https://treasury.nt.gov.au",
        content_type="mixed",
    ),
]


def _slug_to_citation(jurisdiction: str, url: str) -> tuple[str, str]:
    """Derive a readable (citation, title) pair from a ruling URL - these sites
    don't expose a separate title field on the index page, so the URL's last
    path segment (a code like "PTA001" or a descriptive slug) is what we have.
    """
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    name = re.sub(r"\.(pdf|docx|html?)$", "", slug, flags=re.IGNORECASE)
    if re.match(r"^[a-z]+-?\d", name, re.IGNORECASE):
        # Looks like a ruling code (DUT-049, PTA001) - keep it as-is, upper-cased.
        label = name.upper()
    else:
        label = name.replace("-", " ").replace("_", " ").title()
    return f"{jurisdiction} {label}", label


class StateRevenueScraper(ScraperBase):
    """One scraper per jurisdiction, sharing this class - see STATES above for
    what differs (index page, link pattern, content type) per state.
    """

    def __init__(self, config: StateConfig) -> None:
        super().__init__()
        self.config = config
        self.source_name = f"state_revenue_{config.jurisdiction.lower()}"
        self._client.headers["User-Agent"] = BROWSER_UA

    async def fetch_document_list(self) -> list[dict]:
        response = await self._get(self.config.index_url)
        urls: dict[str, str] = {}
        for match in self.config.link_pattern.finditer(response.text):
            href = match.group(0)
            full_url = href if href.startswith("http") else self.config.base_url + href
            urls.setdefault(full_url, full_url)

        documents = []
        for url in urls:
            citation, title = _slug_to_citation(self.config.jurisdiction, url)
            documents.append(
                {
                    "url": url,
                    "title": title,
                    "citation": citation,
                    "source_type": "state_ruling",
                    "effective_date": None,
                    "jurisdiction": self.config.jurisdiction,
                }
            )
        return documents

    def _extract_html_text(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["nav", "header", "footer", "script", "style", "aside"]):
            tag.decompose()
        main = soup.find("main") or soup.find("article") or soup.body or soup
        return main.get_text(separator="\n", strip=True)

    def _extract_pdf_text(self, content: bytes) -> str:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)

    def _extract_docx_text(self, content: bytes) -> str:
        doc = Document(io.BytesIO(content))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

    async def fetch_document_content(self, url: str) -> str:
        response = await self._get(url)
        if response.status_code != 200:
            return ""

        content_type = self.config.content_type
        if content_type == "mixed":
            content_type = "docx" if url.lower().endswith(".docx") else "pdf"

        if content_type == "html":
            return self._extract_html_text(response.text)
        if content_type == "pdf":
            return self._extract_pdf_text(response.content)
        if content_type == "docx":
            return self._extract_docx_text(response.content)
        return ""
