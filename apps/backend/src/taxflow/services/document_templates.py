"""Phase 5: code-owned system-default document-template registry + resolver.

Firms can edit the drafting "template" (the system prompt body) for each
document type in Settings. Resolution is: **firm override body** (a
``document_templates`` row for ``(client_id, template_key)`` with a non-empty
body) **else the code-owned system default** — the current hardcoded prompt
string, moved here verbatim so there is exactly one source of truth and the
fallback is byte-identical to today.

Editable keys = 18 total (Decision #2523):
  - 3 base types that actually have a drafting prompt today: ``advice_memo``,
    ``client_letter``, ``ato_response``.
  - 15 per-ATO-subtype keys ``ato_response:{letter_type}`` over the classifier
    ``LETTER_TYPES``. ATO resolution is subtype-first:
    ``ato_response:{letter_type}`` -> base ``ato_response`` -> system default.

Flags-off / code-owned parity (review B1 + B2):
  - The fixed **role line** is code-owned (``*_ROLE``) and is NOT part of the
    editable body, so the composed prompt keeps the original
    ``role line -> voice_instruction -> rest`` ordering — byte-identical to
    pre-Phase-5 output even for a firm with a ``voice_sample`` and the flag off.
  - The **AU-English guardrail** is a code-owned constant enforced at the
    drafting sites via ``ensure_au_english()`` (OUTSIDE ``resolve_template``), so
    a firm override can never remove or contradict it — it ALWAYS runs. The
    default bodies retain the guardrail inline solely to preserve byte-identical
    flag-off output; ``ensure_au_english`` is idempotent (a no-op when already
    present) and only appends it when a firm's override omits it.

The whole feature is gated behind ``settings.DOCUMENT_TEMPLATES_ENABLED`` so it
can ship dark: when off, ``resolve_template`` always returns the system default.

No raw SQL here — reads go through ``get_relational_data()`` (a provider), so
the ports/adapters boundary is preserved.
"""

from __future__ import annotations

import logging

from taxflow.config import settings
from taxflow.providers import get_relational_data
from taxflow.services.ato_correspondence.classifier import LETTER_TYPES

logger = logging.getLogger(__name__)

# --- code-owned AU-English guardrail (review B2) -----------------------------
# Pulled out of the editable template body: enforced at the drafting sites
# (draft.py, document_graph.py) regardless of the flag or any firm override, so
# a firm can never disable the AU-English drafting instruction.
AU_ENGLISH_MARKER = "Use Australian English"
AU_ENGLISH_GUARDRAIL = (
    "Use Australian English: organisation, recognise, licence (noun), practise (verb), "
    "lodgement, cheque, programme, centre, labour, behaviour."
)
# The full guardrail SEMANTICS: the marker phrase plus every required AU-English
# term. Presence is judged on ALL of these (after whitespace normalisation), not
# on the marker substring alone — so a firm override that merely mentions
# "Use Australian English loosely" (marker present, terms absent) can't suppress
# the real guardrail.
_AU_ENGLISH_REQUIRED_TERMS = (
    AU_ENGLISH_MARKER,
    "organisation",
    "recognise",
    "licence (noun)",
    "practise (verb)",
    "lodgement",
    "cheque",
    "programme",
    "centre",
    "labour",
    "behaviour",
)


def _au_english_present(system: str) -> bool:
    """True only when the FULL code-owned guardrail semantics are present. The
    code-owned default bodies embed a line-wrapped copy, so normalise whitespace
    (collapse runs of whitespace to single spaces) before checking every
    required term."""
    normalised = " ".join(system.split())
    return all(term in normalised for term in _AU_ENGLISH_REQUIRED_TERMS)


def ensure_au_english(system: str) -> str:
    """Guarantee the code-owned AU-English guardrail is present in a composed
    system prompt. Idempotent: when the full guardrail semantics are already
    present (the code-owned default bodies keep it inline for byte-identical
    flag-off parity) this is a no-op; when a firm's override omitted or weakened
    it, the exact ``AU_ENGLISH_GUARDRAIL`` is appended so it ALWAYS runs."""
    if _au_english_present(system):
        return system
    if system.endswith("\n\n"):
        sep = ""
    elif system.endswith("\n"):
        sep = "\n"
    else:
        sep = "\n\n"
    return f"{system}{sep}{AU_ENGLISH_GUARDRAIL}"


# --- code-owned fixed role lines (review B1) ---------------------------------
# Kept out of the editable body so the composed prompt preserves the original
# ``role line -> voice_instruction -> rest`` ordering.
ADVICE_MEMO_ROLE = "You are drafting a tax advice memo for an Australian accounting firm.\n"
CLIENT_LETTER_ROLE = (
    "You are drafting a letter from an Australian accounting firm directly to their client.\n"
)


# --- system-default prompt bodies (the editable "rest", moved verbatim) -------
# These are everything AFTER the code-owned role line + voice_instruction. They
# still contain the AU-English guardrail inline so that, with the flag off, the
# composed prompt is byte-identical to the pre-Phase-5 string; ensure_au_english
# guarantees the guardrail for firm overrides that omit it.

# advice_memo — from services/agents/draft.py (post role line + voice).
ADVICE_MEMO_DEFAULT = (
    "Structure requirements (all sections mandatory):\n"
    "1. SUMMARY (2-3 sentences): Direct answer to the question asked.\n"
    "2. LEGISLATIVE FRAMEWORK: Key legislation and ATO positions that apply.\n"
    "   Cite every section using the reference numbers from the research.\n"
    "3. APPLICATION TO FACTS: How the law applies to this specific situation.\n"
    "4. CONCLUSION AND RECOMMENDED ACTION: What the client should do.\n"
    "5. IMPORTANT LIMITATIONS: Note that this is AI-assisted advice requiring\n"
    "   professional review before reliance.\n\n"
    "Use Australian English: organisation, recognise, licence (noun), practise (verb),\n"
    "lodgement, cheque, programme, centre, labour, behaviour.\n\n"
    "Do not include: generic disclaimers like 'this is general advice only',\n"
    "American spellings, passive voice without justification."
)

# client_letter — from services/agents/document_graph.py (post role line + voice).
CLIENT_LETTER_DEFAULT = (
    "This is a CLIENT-FACING letter, not an internal working paper - write it accordingly:\n"
    "- Open with a plain-English greeting and state the purpose in the first paragraph.\n"
    "- Explain the advice in plain English. Do not use internal section headers like "
    "'SUMMARY' or 'LEGISLATIVE FRAMEWORK', and do not use retrieval/citation-marker notation "
    "like [1] - if you reference a ruling or provision, name it in the sentence itself.\n"
    "- Close with a short next-steps paragraph and a signature block "
    "('Kind regards,' on its own line, firm name below it).\n\n"
    "Use Australian English: organisation, recognise, licence (noun), practise (verb), "
    "lodgement, cheque, programme, centre, labour, behaviour.\n\n"
    "Do not include generic disclaimers like 'this is general advice only', American "
    "spellings, or internal jargon a client wouldn't recognise."
)

# ato_response — from services/ato_correspondence/drafter.py SYSTEM_PROMPT (no
# voice/role split; used as the full system prompt).
ATO_RESPONSE_DEFAULT = """You are drafting a formal letter to the Australian Taxation Office on behalf of
an Australian taxpayer. This is a professional correspondence.

Format requirements:
- Start: 'Dear Commissioner' or 'To the Commissioner of Taxation'
- Reference line: 'Re: [ATO Reference Number from letter]'
- Our reference: '[TaxFlow ref: TF-{date}-{id}]'
- Acknowledge the ATO letter by date and reference number in first paragraph
- Address each issue raised by the ATO specifically
- Close: 'Yours faithfully'
- Signature block: '[Firm name] | [Date]'
- Maximum 2 pages (approximately 600 words)

Tone: Professional, factual, non-confrontational unless disputing.
Never: aggressive, emotional, or personal."""


def ato_subtype_key(letter_type: str) -> str:
    """The per-ATO-subtype template key for a classifier letter type."""
    return f"ato_response:{letter_type}"


# --- 18 editable keys: 3 base + 15 per-ATO-subtype ---------------------------

SYSTEM_DEFAULTS: dict[str, str] = {
    "advice_memo": ADVICE_MEMO_DEFAULT,
    "client_letter": CLIENT_LETTER_DEFAULT,
    "ato_response": ATO_RESPONSE_DEFAULT,
    # Per-ATO-subtype defaults start as the base ato_response prompt until a firm
    # customises them; the base key is the fallthrough between subtype and the
    # system default.
    **{ato_subtype_key(lt): ATO_RESPONSE_DEFAULT for lt in LETTER_TYPES},
}

# Human-readable labels for the Settings list (18 entries).
_ATO_SUBTYPE_LABELS = {
    "bas_discrepancy": "BAS discrepancy",
    "audit_initiation": "Audit initiation",
    "penalty_notice": "Penalty notice",
    "garnishee_notice": "Garnishee notice",
    "position_paper": "Position paper",
    "objection_result": "Objection result",
    "ato_debt_notice": "ATO debt notice",
    "payment_plan_request": "Payment plan request",
    "lodgement_reminder": "Lodgement reminder",
    "audit_completion": "Audit completion",
    "abn_cancellation": "ABN cancellation",
    "gst_registration": "GST registration",
    "employer_obligations": "Employer obligations",
    "lifestyle_assets": "Lifestyle assets",
    "taxable_payments": "Taxable payments",
}

TEMPLATE_LABELS: dict[str, str] = {
    "advice_memo": "Tax advice memo",
    "client_letter": "Client letter",
    "ato_response": "ATO response (default)",
    **{
        ato_subtype_key(lt): f"ATO response - {_ATO_SUBTYPE_LABELS.get(lt, lt)}"
        for lt in LETTER_TYPES
    },
}


def _row_body(row: dict | None) -> str | None:
    """Return a usable override body from a template row, or None. A row counts
    as an override when it has a non-empty body (there is no soft-delete state
    today; see the ``is_active`` note in migration 041)."""
    if row and (row.get("body") or "").strip():
        return row["body"]
    return None


def _firm_body(client_id: str, template_key: str) -> str | None:
    """Return the firm's non-empty override body for ``template_key`` or None.
    Best-effort: on DB error, log and return None so callers fall back to the
    system default (drafting must never be blocked by a template lookup)."""
    if not settings.DOCUMENT_TEMPLATES_ENABLED:
        return None
    try:
        row = get_relational_data().document_templates.get_for_key(client_id, template_key)
    except Exception:  # noqa: BLE001 - never block drafting on a template lookup
        logger.exception("document_templates lookup failed for key=%s", template_key)
        return None
    return _row_body(row)


def _resolve_from(get_body, template_key: str) -> str:
    """Shared subtype->base->system-default resolution over a ``get_body(key)``
    lookup (a per-key DB call for ``resolve_template`` or an in-memory map
    lookup for ``list_templates_for_client``)."""
    if template_key.startswith("ato_response:"):
        return (
            get_body(template_key)
            or get_body("ato_response")
            or SYSTEM_DEFAULTS[template_key]
        )
    return get_body(template_key) or SYSTEM_DEFAULTS[template_key]


def resolve_template(client_id: str, template_key: str) -> str:
    """Resolve the system-prompt BODY for ``template_key`` (the editable part,
    excluding the code-owned role line + AU-English guardrail).

    For a per-ATO-subtype key ``ato_response:{letter_type}`` resolution is
    subtype-first: firm subtype row -> firm base ``ato_response`` row -> system
    default. For any other key: firm row -> system default. Unknown keys raise
    ``KeyError`` (callers pass a key from ``SYSTEM_DEFAULTS``)."""
    if template_key not in SYSTEM_DEFAULTS:
        raise KeyError(f"unknown template_key: {template_key}")
    return _resolve_from(lambda key: _firm_body(client_id, key), template_key)


def list_templates_for_client(client_id: str) -> list[dict]:
    """For each editable key, return the resolved body + whether the firm has a
    custom row. Used by ``GET /settings/templates``.

    Single-query (review S1): the firm's rows are fetched once and resolution +
    the ``is_custom`` flag are computed in-memory off that map, instead of
    re-hitting the DB per key via ``resolve_template``."""
    rows_by_key: dict[str, dict] = {}
    if settings.DOCUMENT_TEMPLATES_ENABLED:
        try:
            for r in get_relational_data().document_templates.list_for_client(client_id):
                rows_by_key[r["template_key"]] = r
        except Exception:  # noqa: BLE001 - degrade to defaults, never 500 the list
            logger.exception("document_templates list failed for client")

    def get_body(key: str) -> str | None:
        return _row_body(rows_by_key.get(key))

    out: list[dict] = []
    for key in SYSTEM_DEFAULTS:
        out.append(
            {
                "template_key": key,
                "label": TEMPLATE_LABELS.get(key, key),
                "body": _resolve_from(get_body, key),
                # is_custom = the firm has its OWN row for this exact key.
                "is_custom": get_body(key) is not None,
            }
        )
    return out
