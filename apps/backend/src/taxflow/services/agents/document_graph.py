"""LangGraph pipeline for turning a saved answer into a specific document type.

Separate from ``research_graph`` (services/agents/graph.py) on purpose:
``research_graph`` runs automatically on every question; this graph runs only
when a user deliberately clicks "Save as document" for one specific type -
a different trigger, so it stays a different graph rather than a branch
inside the live query pipeline.

``route_by_type`` is a plain Python dict-style lookup on ``document_type``,
which the user already picked from a dropdown before saving - there is no
LLM decision about WHICH type to produce, only (for two of the types) an LLM
call that reformats the content once the type is already fixed. This replaces
the single ad-hoc `if document_type == "advice_memo"` branch that used to live
in routers/documents.py with one node per type and per-node error isolation,
instead of one top-level `except Exception: pass` swallowing every type's
failures identically.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from taxflow import providers
from taxflow.providers import get_relational_data
from taxflow.services.agents.draft import DraftAgent
from taxflow.services.document_templates import (
    CLIENT_LETTER_ROLE,
    ensure_au_english,
    resolve_template,
)

drafter = DraftAgent()

# Types that go through their own reformatting node; everything else in
# TEMPLATE_REGISTRY (routers/documents.py) passes through unchanged, matching
# behaviour before this graph existed.
_REFORMAT_TYPES = {"advice_memo", "client_letter"}


class DocumentState(TypedDict, total=False):
    document_type: str
    content_md: str
    original_question: str | None
    citations: list[dict]
    client_id: str
    result_md: str
    error: str | None


def route_by_type(state: DocumentState) -> str:
    document_type = state["document_type"]
    if document_type in _REFORMAT_TYPES:
        return document_type
    return "passthrough"


async def draft_advice_memo(state: DocumentState) -> dict:
    """Reformat into the firm's fixed 5-section internal working-paper
    structure (unchanged behaviour, now isolated to its own node)."""
    try:
        result = await drafter.run(
            research_result={"answer": state["content_md"], "citations": state.get("citations") or []},
            original_question=state.get("original_question") or "",
            client_id=state["client_id"],
        )
        return {"result_md": result["draft"]}
    except Exception as e:  # noqa: BLE001 - drafting failure must not block saving
        return {"result_md": state["content_md"], "error": str(e)}


async def draft_client_letter(state: DocumentState) -> dict:
    """Reformat into a client-facing letter: plain-English, no internal
    section headers or retrieval jargon, closing signature block - distinct
    from advice_memo's internal working-paper structure (the panel's
    "keep these as separate document types" finding)."""
    try:
        voice_sample = get_relational_data().clients.get_voice_sample(state["client_id"]) or ""
        voice_instruction = (
            f"The firm describes its own voice like this - match this tone:\n\"{voice_sample}\"\n\n"
            if voice_sample
            else ""
        )
        # Code-owned role line -> per-firm voice_instruction -> resolved body
        # (review B1 ordering); AU-English guardrail enforced code-owned
        # (review B2), idempotent so the default is byte-identical.
        system = ensure_au_english(
            f"{CLIENT_LETTER_ROLE}"
            f"{voice_instruction}"
            f"{resolve_template(state['client_id'], 'client_letter')}"
        )
        user = (
            f"Rewrite this internal research answer as a client letter:\n{state['content_md']}\n\n"
            f"The original question was: {state.get('original_question') or ''}"
        )
        result = await providers.get_llm().generate(
            messages=[{"role": "user", "content": user}],
            system=system,
            model=providers.resolve_model("draft"),
            max_tokens=2000,
            temperature=0.1,
        )
        letter = drafter._americanism_fix(result.text)
        return {"result_md": letter}
    except Exception as e:  # noqa: BLE001 - drafting failure must not block saving
        return {"result_md": state["content_md"], "error": str(e)}


async def passthrough(state: DocumentState) -> dict:
    """Every other document_type in TEMPLATE_REGISTRY: content_md is saved
    unchanged, matching behaviour before this graph existed."""
    return {"result_md": state["content_md"]}


def build_document_graph() -> Any:
    g = StateGraph(DocumentState)
    g.add_node("draft_advice_memo", draft_advice_memo)
    g.add_node("client_letter", draft_client_letter)
    g.add_node("passthrough", passthrough)

    g.add_conditional_edges(
        START,
        route_by_type,
        {
            "advice_memo": "draft_advice_memo",
            "client_letter": "client_letter",
            "passthrough": "passthrough",
        },
    )
    g.add_edge("draft_advice_memo", END)
    g.add_edge("client_letter", END)
    g.add_edge("passthrough", END)
    return g.compile()


document_graph = build_document_graph()
