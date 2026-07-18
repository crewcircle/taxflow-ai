"""Thin shim delegating source-PDF storage to the ObjectStoragePort.

The concrete implementation now lives in
``taxflow.adapters.storage.s3.S3ObjectStorageAdapter`` and is resolved via
``taxflow.providers.get_object_storage()``. These module-level functions are
kept so existing call sites (routers/knowledge.py, scrapers/ato_rulings.py,
scraper_base.py) need no changes; each simply forwards to the port, which
degrades gracefully (returns None) when R2 is unconfigured.
"""

from __future__ import annotations

from taxflow.providers import get_object_storage


def object_key_for(source_url: str) -> str:
    return get_object_storage().object_key_for(source_url)


def upload_source_pdf(source_url: str, content: bytes) -> str | None:
    """Upload a source PDF's raw bytes; returns the object key or None."""
    return get_object_storage().upload_source_pdf(source_url, content)


def get_source_pdf_url(object_key: str) -> str | None:
    """Signed, time-limited URL to view a stored source PDF, or None."""
    return get_object_storage().get_signed_url(object_key)
