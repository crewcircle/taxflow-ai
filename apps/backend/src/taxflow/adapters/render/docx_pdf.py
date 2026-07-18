"""Default DocumentRenderPort adapter (Task B9).

Wraps the existing ``services.export.generate_docx`` / ``generate_pdf``
implementations (python-docx + weasyprint) behind
:class:`taxflow.ports.scrapers.DocumentRenderPort`. The adapter does not change
how docx/pdf are generated — it merely delegates to the underlying functions so
document-download routes can depend on the port via
``providers.get_document_renderer()`` instead of importing ``export`` directly.

``doc`` is a plain dict carrying the fields the export functions need:
``content_md``, ``title``, ``client_name`` and ``date``.
"""

from __future__ import annotations

from taxflow.services.export import generate_docx, generate_pdf


class DocxPdfRenderer:
    """DocumentRenderPort adapter backed by python-docx + weasyprint."""

    def render_docx(self, doc: dict) -> bytes:
        return generate_docx(
            doc["content_md"],
            doc["title"],
            doc["client_name"],
            doc["date"],
        )

    def render_pdf(self, doc: dict) -> bytes:
        return generate_pdf(
            doc["content_md"],
            doc["title"],
            doc["client_name"],
            doc["date"],
        )
