"""Port Protocols for the AI-core (LLM) subsystem.

Business/agent code depends on these structural types; concrete adapters live in
``taxflow.adapters.llm``. Kept intentionally small: single-shot generate,
streaming generate, and structured (Pydantic-validated) generate, plus a usage
record that preserves the four token counters the persistence layer stores today.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol, Sequence, runtime_checkable

from pydantic import BaseModel


@dataclass
class Usage:
    """Token usage, mapping both Anthropic- and OpenAI-style field names."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    def as_dict(self) -> dict[str, int]:
        """The four token counters as a plain dict, for the persistence layer."""
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
        }


@dataclass
class LLMResult:
    text: str
    usage: Usage = field(default_factory=Usage)


@dataclass
class StreamChunk:
    """A streaming event. Text chunks carry ``text``; the terminal chunk carries
    ``usage`` and ``done=True`` (and may have empty text)."""

    text: str = ""
    usage: Usage | None = None
    done: bool = False


class StructuredParseError(Exception):
    """Raised when a structured (JSON) generation cannot be validated into the
    requested Pydantic model. Callers fall back to their tolerant parser."""


# A system prompt is either a plain string or a provider-neutral list of content
# blocks (the prompt-cache representation; LiteLLM forwards cache_control to
# Anthropic and no-ops elsewhere).
SystemPrompt = str | list[dict[str, Any]]
Messages = Sequence[dict[str, Any]]


@runtime_checkable
class LLMPort(Protocol):
    async def generate(
        self,
        *,
        messages: Messages,
        system: SystemPrompt | None = None,
        model: str,
        max_tokens: int,
        temperature: float = 0.0,
    ) -> LLMResult: ...

    def stream(
        self,
        *,
        messages: Messages,
        system: SystemPrompt | None = None,
        model: str,
        max_tokens: int,
        temperature: float = 0.0,
    ) -> AsyncIterator[StreamChunk]: ...

    async def generate_structured(
        self,
        *,
        messages: Messages,
        system: SystemPrompt | None = None,
        model: str,
        output_model: type[BaseModel],
        max_tokens: int,
        temperature: float = 0.0,
    ) -> BaseModel: ...
