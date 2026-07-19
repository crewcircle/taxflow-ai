"""Shared tolerant JSON extraction.

LLMs frequently wrap JSON in ```` ```json ```` fences or surround it with prose
despite instructions to emit JSON only. :func:`extract_json_object` recovers the
first JSON *object* from such output. Callers layer their own domain-specific
fallback (e.g. a ``parse_error`` verdict) on top when this returns ``None``.
"""

from __future__ import annotations

import json
import re


def extract_json_object(text: str) -> dict | None:
    """Return the first JSON object in ``text``, or ``None`` if none parses.

    Tries, in order: direct ``json.loads``; fence-stripped ``json.loads``; the
    first balanced ``{...}`` object found anywhere in the text. Only dict-shaped
    results are returned; a parsed non-dict (list/number) yields ``None``.
    """
    text = (text or "").strip()

    def _try(candidate: str) -> dict | None:
        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None

    result = _try(text)
    if result is not None:
        return result

    if text.startswith("```"):
        stripped = text.split("\n", 1)[1] if "\n" in text else text
        stripped = stripped.rsplit("```", 1)[0].strip()
        result = _try(stripped)
        if result is not None:
            return result

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        result = _try(match.group(0))
        if result is not None:
            return result

    return None
