"""Port Protocol for text embeddings."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingPort(Protocol):
    async def embed(self, text: str) -> list[float]: ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...

    @property
    def dimension(self) -> int: ...
