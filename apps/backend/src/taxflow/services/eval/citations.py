"""Deterministic citation-validity checker (Task B1).

Validates the ``[N]`` markers a model emitted in its answer against the list of
sources it *actually saw* — the rendered source list. No LLM, no DB.

Rendered vs raw candidates
--------------------------
Under parent-expansion (Workstream C) several raw candidate chunks can collapse
into fewer rendered blocks, so the number the model can legally cite is
``len(rendered_sources)``, NOT ``len(candidates)``. We therefore validate
against ``trace.retrieval.rendered_sources`` when present, falling back to
``trace.retrieval.candidates`` for legacy / flag-off traces where the two lists
are identical one-to-one.

A ``[3]`` that was never rendered is flagged *fabricated* even though three raw
candidates existed — which is the whole point of reading the rendered list.
"""

from __future__ import annotations

from taxflow.services.agents.research import CITATION_PATTERN


def _rendered_sources(result: dict) -> list[dict]:
    """The ordered list of sources the model actually saw.

    Prefer ``trace.retrieval.rendered_sources`` (produced by Workstream C's
    parent-expansion rendering); fall back to ``trace.retrieval.candidates`` for
    legacy / flag-off traces. Read everything defensively with ``.get()`` so a
    partial or pre-C trace never raises.
    """
    retrieval = ((result or {}).get("trace") or {}).get("retrieval") or {}
    rendered = retrieval.get("rendered_sources")
    if rendered is None:
        rendered = retrieval.get("candidates") or []
    return list(rendered)


def check_citation_validity(result: dict) -> dict:
    """Check a ``run()``-shaped result's citations against the rendered sources.

    Returns::

        {
          "valid": bool,                     # no fabricated markers, no unmatched
          "fabricated_markers": list[int],   # [N] with N outside 1..len(rendered)
          "unmatched_citations": list[str],  # parsed citation not in rendered set
          "total_citations": int,            # distinct [N] markers found
        }

    - "fabricated" = a ``[N]`` marker whose index is outside
      ``1..len(rendered_sources)`` (a source the model never saw).
    - "unmatched" = a parsed ``citations[].citation`` that does not appear in the
      rendered sources' ``citation`` field.
    """
    rendered = _rendered_sources(result)
    n_rendered = len(rendered)

    answer = (result or {}).get("answer") or ""
    marker_numbers = sorted({int(n) for n in CITATION_PATTERN.findall(answer)})
    fabricated = [n for n in marker_numbers if n < 1 or n > n_rendered]

    rendered_citations = {
        (src.get("citation") or "").strip()
        for src in rendered
        if isinstance(src, dict)
    }
    parsed = (result or {}).get("citations") or []
    unmatched = [
        (c.get("citation") or "").strip()
        for c in parsed
        if isinstance(c, dict)
        and (c.get("citation") or "").strip() not in rendered_citations
    ]

    return {
        "valid": not fabricated and not unmatched,
        "fabricated_markers": fabricated,
        "unmatched_citations": unmatched,
        "total_citations": len(marker_numbers),
    }
