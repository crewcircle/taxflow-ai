"""Default TokenizerPort adapter (Task B9).

Wraps tiktoken behind :class:`taxflow.ports.scrapers.TokenizerPort`, isolating
the OpenAI-tokenizer assumption behind ``config.TOKENIZER_MODEL`` (default
``cl100k_base``). The encoding is built lazily and memoised so importing this
module never touches tiktoken's registry.
"""

from __future__ import annotations

import tiktoken

from taxflow.config import settings


class TiktokenTokenizer:
    """TokenizerPort adapter backed by tiktoken."""

    def __init__(self) -> None:
        self._encoding = None

    def _get_encoding(self):
        """Lazily build and memoise the tiktoken encoding."""
        if self._encoding is None:
            self._encoding = tiktoken.get_encoding(settings.TOKENIZER_MODEL)
        return self._encoding

    def encode(self, text: str) -> list[int]:
        return self._get_encoding().encode(text)

    def count(self, text: str) -> int:
        return len(self.encode(text))
