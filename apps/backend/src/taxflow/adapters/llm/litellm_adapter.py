"""LiteLLM adapter implementing :class:`taxflow.ports.llm.LLMPort` (Task A1).

LiteLLM gives us a single vendor-neutral client (``litellm.acompletion``) that
routes to Anthropic today and to any other provider by changing the ``model``
string. This adapter maps LiteLLM's response shape onto the port's small
``LLMResult``/``StreamChunk``/``Usage`` records, normalising the two token-usage
naming conventions (Anthropic ``input_tokens`` vs OpenAI ``prompt_tokens``) and
prefixing bare Claude IDs so callers that pass ``settings.VERIFY_MODEL`` /
``ANTHROPIC_*_MODEL`` (which are un-prefixed) still route to Anthropic.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from pydantic import BaseModel, ValidationError

from taxflow.ports.llm import (
    LLMResult,
    Messages,
    StreamChunk,
    StructuredParseError,
    SystemPrompt,
    Usage,
)

import litellm


def _normalize_model(model: str) -> str:
    """Prefix bare Claude IDs (no provider prefix) with ``anthropic/``.

    ``providers.resolve_model`` prefixes tier names, but callers may pass raw
    Claude model IDs (e.g. ``settings.VERIFY_MODEL == "claude-haiku-4-5"``).
    Without a provider prefix LiteLLM cannot route them, so add it defensively.
    Leaves anything already containing "/" (an explicit provider route) intact.
    """
    if "/" not in model and model.startswith("claude"):
        return f"anthropic/{model}"
    return model


def _map_usage(u: Any) -> Usage:
    """Map a LiteLLM usage object onto :class:`Usage`, handling both
    Anthropic-style (``input_tokens``) and OpenAI-style (``prompt_tokens``)
    field names, including OpenAI's nested cached-token counter."""
    if u is None:
        return Usage()
    input_tokens = getattr(u, "input_tokens", None) or getattr(u, "prompt_tokens", 0) or 0
    output_tokens = (
        getattr(u, "output_tokens", None) or getattr(u, "completion_tokens", 0) or 0
    )
    cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
    if not cache_read:
        details = getattr(u, "prompt_tokens_details", None)
        cache_read = getattr(details, "cached_tokens", 0) or 0
    cache_creation = getattr(u, "cache_creation_input_tokens", 0) or 0
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_creation,
    )


def _build_messages(messages: Messages, system: SystemPrompt | None) -> list[dict]:
    """Prepend a system message (plain string or provider-neutral content
    blocks) when present. LiteLLM forwards ``cache_control`` blocks to Anthropic
    and no-ops them elsewhere."""
    if system:
        return [{"role": "system", "content": system}, *messages]
    return list(messages)


class LiteLLMAdapter:
    """Concrete :class:`LLMPort` backed by ``litellm.acompletion``."""

    def __init__(self, api_key: str | None = None, api_base: str | None = None) -> None:
        # The composition root injects the configured provider key (e.g.
        # ``settings.ANTHROPIC_API_KEY``). Pydantic ``BaseSettings(env_file=...)``
        # does NOT export values into ``os.environ``, so relying on LiteLLM's
        # implicit env lookup would break any deployment/local run that supplies
        # keys only via ``apps/backend/.env``. Passing the key explicitly (None
        # falls back to LiteLLM's env lookup) keeps both paths working.
        self._api_key = api_key or None
        # Optional OpenAI-compatible base URL (e.g. OpenCode). ``None`` preserves
        # the current Anthropic behaviour (LiteLLM uses its default endpoints).
        self._api_base = api_base or None

    async def generate(
        self,
        *,
        messages: Messages,
        system: SystemPrompt | None = None,
        model: str,
        max_tokens: int,
        temperature: float = 0.0,
    ) -> LLMResult:
        resp = await litellm.acompletion(
            model=_normalize_model(model),
            messages=_build_messages(messages, system),
            max_tokens=max_tokens,
            temperature=temperature,
            api_key=self._api_key,
            api_base=self._api_base,
        )
        text = resp.choices[0].message.content or ""
        usage = _map_usage(getattr(resp, "usage", None))
        return LLMResult(text=text, usage=usage)

    def stream(
        self,
        *,
        messages: Messages,
        system: SystemPrompt | None = None,
        model: str,
        max_tokens: int,
        temperature: float = 0.0,
    ) -> AsyncIterator[StreamChunk]:
        """Return an async iterator of stream chunks.

        This is a *sync* method (matching the port signature) that returns an
        async generator, so callers write ``async for chunk in llm.stream(...)``
        with no ``await`` on the ``stream()`` call itself.
        """

        async def _gen() -> AsyncIterator[StreamChunk]:
            stream = await litellm.acompletion(
                model=_normalize_model(model),
                messages=_build_messages(messages, system),
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
                stream_options={"include_usage": True},
                api_key=self._api_key,
                api_base=self._api_base,
            )
            final_usage: Usage | None = None
            async for chunk in stream:
                choices = getattr(chunk, "choices", None) or []
                if choices:
                    delta = getattr(choices[0], "delta", None)
                    content = getattr(delta, "content", None) if delta else None
                    if content:
                        yield StreamChunk(text=content)
                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    final_usage = _map_usage(usage)
            yield StreamChunk(usage=final_usage or Usage(), done=True)

        return _gen()

    async def generate_structured(
        self,
        *,
        messages: Messages,
        system: SystemPrompt | None = None,
        model: str,
        output_model: type[BaseModel],
        max_tokens: int,
        temperature: float = 0.0,
    ) -> BaseModel:
        resp = await litellm.acompletion(
            model=_normalize_model(model),
            messages=_build_messages(messages, system),
            max_tokens=max_tokens,
            temperature=temperature,
            response_format=output_model,
            api_key=self._api_key,
            api_base=self._api_base,
        )
        content = resp.choices[0].message.content or ""
        try:
            return output_model.model_validate_json(content)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise StructuredParseError(
                f"Failed to parse structured output into {output_model.__name__}: {exc}"
            ) from exc
