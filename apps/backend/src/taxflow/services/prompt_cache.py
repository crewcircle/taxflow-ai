"""Shared Anthropic prompt-caching helper (Task B1).

Large static system prompts form a stable cacheable prefix. Marking them
`cache_control: ephemeral` lets repeat calls read them from cache at ~10% of the
input price. When PROMPT_CACHE_ENABLED is False we fall back to the plain string
form the API also accepts. Centralised here so research/verify/classifier/drafter
all build the system parameter identically instead of copy-pasting the block.
"""
from taxflow.config import settings


def cacheable_system(prompt: str) -> list[dict] | str:
    """Return `prompt` as an ephemeral-cache content block, or the plain string
    when prompt caching is disabled.

    The returned shape is the provider-neutral ``system`` input carried by the
    LLMPort: a list of ``{"type": "text", "text": ..., "cache_control": ...}``
    content blocks. LiteLLM forwards ``cache_control`` to Anthropic (enabling
    prompt caching) and no-ops it for other providers, so the same shape is safe
    everywhere. The shape MUST stay identical (see test_prompt_caching.py)."""
    if not settings.PROMPT_CACHE_ENABLED:
        return prompt
    return [{"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}]
