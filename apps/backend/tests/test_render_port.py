"""Tests for the DocumentRenderPort adapter (Task B9)."""

from taxflow import providers
from taxflow.adapters.render.docx_pdf import DocxPdfRenderer
from taxflow.ports.scrapers import DocumentRenderPort

SAMPLE_DOC = {
    "content_md": "# Heading\n\nSome advice text.\n\n## Section\n\nMore detail here.",
    "title": "Sample advice memo",
    "client_name": "Acme Pty Ltd",
    "date": "2026-07-18",
}


def test_renderer_implements_port():
    assert isinstance(DocxPdfRenderer(), DocumentRenderPort)


def test_render_docx_returns_non_empty_bytes():
    content = DocxPdfRenderer().render_docx(SAMPLE_DOC)
    assert isinstance(content, bytes)
    assert len(content) > 0
    # docx files are zip archives ("PK" magic).
    assert content[:2] == b"PK"


def test_render_pdf_returns_non_empty_bytes():
    content = DocxPdfRenderer().render_pdf(SAMPLE_DOC)
    assert isinstance(content, bytes)
    assert len(content) > 0
    assert content[:4] == b"%PDF"


def test_provider_resolves_default_adapter():
    providers.reset_providers()
    renderer = providers.get_document_renderer()
    assert isinstance(renderer, DocxPdfRenderer)
    assert isinstance(renderer, DocumentRenderPort)
