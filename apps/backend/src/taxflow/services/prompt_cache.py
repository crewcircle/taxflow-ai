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
    when prompt caching is disabled."""
    if not settings.PROMPT_CACHE_ENABLED:
        return prompt
    return [{"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}]
