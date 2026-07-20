"""Phase 5: code-owned system-default document-template registry + resolver.

Firms can edit the drafting "template" (the system prompt body) for each
document type in Settings. Resolution is: **firm override body** (a
``document_templates`` row for ``(client_id, template_key)`` with a non-empty
body and ``is_active``) **else the code-owned system default** — the current
hardcoded prompt string, moved here verbatim so there is exactly one source of
truth and the fallback is byte-identical to today.

Editable keys = 18 total (Decision #2523):
  - 3 base types that actually have a drafting prompt today: ``advice_memo``,
    ``client_letter``, ``ato_response``.
  - 15 per-ATO-subtype keys ``ato_response:{letter_type}`` over the classifier
    ``LETTER_TYPES``. ATO resolution is subtype-first:
    ``ato_response:{letter_type}`` -> base ``ato_response`` -> system default.

The AU-English fix + ``REQUIRED_SECTIONS`` section-presence retry stay OUTSIDE
the editable body and always run (code-owned guardrails a firm cannot disable).

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

# --- system-default prompt bodies (moved verbatim from the drafting sites) ----

# advice_memo — from services/agents/draft.py (the static part; the per-firm
# voice_instruction is prepended by the drafting site, not part of the body).
ADVICE_MEMO_DEFAULT = (
    "You are drafting a tax advice memo for an Australian accounting firm.\n"
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

# client_letter — from services/agents/document_graph.py (static part; the
# per-firm voice_instruction is prepended by the drafting site).
CLIENT_LETTER_DEFAULT = (
    "You are drafting a letter from an Australian accounting firm directly to their client.\n"
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

# ato_response — from services/ato_correspondence/drafter.py SYSTEM_PROMPT.
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


def _firm_body(client_id: str, template_key: str) -> str | None:
    """Return the firm's active, non-empty override body for ``template_key`` or
    None. Best-effort: on DB error, log and return None so callers fall back to
    the system default (drafting must never be blocked by a template lookup)."""
    if not settings.DOCUMENT_TEMPLATES_ENABLED:
        return None
    try:
        row = get_relational_data().document_templates.get_for_key(client_id, template_key)
    except Exception:  # noqa: BLE001 - never block drafting on a template lookup
        logger.exception("document_templates lookup failed for key=%s", template_key)
        return None
    if row and row.get("is_active") and (row.get("body") or "").strip():
        return row["body"]
    return None


def resolve_template(client_id: str, template_key: str) -> str:
    """Resolve the system-prompt body for ``template_key``.

    For a per-ATO-subtype key ``ato_response:{letter_type}`` resolution is
    subtype-first: firm subtype row -> firm base ``ato_response`` row -> system
    default. For any other key: firm row -> system default. Unknown keys raise
    ``KeyError`` (callers pass a key from ``SYSTEM_DEFAULTS``)."""
    if template_key not in SYSTEM_DEFAULTS:
        raise KeyError(f"unknown template_key: {template_key}")

    # Subtype-first fallthrough for ATO subtype keys.
    if template_key.startswith("ato_response:"):
        body = _firm_body(client_id, template_key)
        if body is not None:
            return body
        base = _firm_body(client_id, "ato_response")
        if base is not None:
            return base
        return SYSTEM_DEFAULTS[template_key]

    body = _firm_body(client_id, template_key)
    if body is not None:
        return body
    return SYSTEM_DEFAULTS[template_key]


def list_templates_for_client(client_id: str) -> list[dict]:
    """For each editable key, return the resolved body + whether the firm has a
    custom row. Used by ``GET /settings/templates``."""
    custom_keys: set[str] = set()
    if settings.DOCUMENT_TEMPLATES_ENABLED:
        try:
            rows = get_relational_data().document_templates.list_for_client(client_id)
            custom_keys = {
                r["template_key"]
                for r in rows
                if r.get("is_active") and (r.get("body") or "").strip()
            }
        except Exception:  # noqa: BLE001 - degrade to defaults, never 500 the list
            logger.exception("document_templates list failed for client")

    out: list[dict] = []
    for key in SYSTEM_DEFAULTS:
        out.append(
            {
                "template_key": key,
                "label": TEMPLATE_LABELS.get(key, key),
                "body": resolve_template(client_id, key),
                "is_custom": key in custom_keys,
            }
        )
    return out
