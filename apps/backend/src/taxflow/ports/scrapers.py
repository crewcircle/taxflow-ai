"""Port Protocols for source scrapers, document rendering, and tokenization."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SourceScraperPort(Protocol):
    source_name: str

    async def fetch_document_list(self) -> list[dict]: ...

    async def fetch_document_content(self, url: str) -> str: ...

    async def run_delta(self, limit: int | None = None) -> int: ...

    async def aclose(self) -> None: ...


@runtime_checkable
class DocumentRenderPort(Protocol):
    def render_docx(self, doc: dict) -> bytes: ...

    def render_pdf(self, doc: dict) -> bytes: ...


@runtime_checkable
class TokenizerPort(Protocol):
    def encode(self, text: str) -> list[int]: ...

    def count(self, text: str) -> int: ...
