"""Port Protocol for object storage (source PDFs)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ObjectStoragePort(Protocol):
    def object_key_for(self, source_url: str) -> str:
        """Deterministic object key for a source URL."""
        ...

    def upload_source_pdf(self, source_url: str, content: bytes) -> str | None:
        """Store raw PDF bytes; return the object key, or None if unconfigured."""
        ...

    def get_signed_url(self, object_key: str) -> str | None:
        """Signed, time-limited URL for a stored object, or None if unconfigured."""
        ...
