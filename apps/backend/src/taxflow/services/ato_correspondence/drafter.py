from datetime import date

from taxflow import providers
from taxflow.services.document_templates import ato_subtype_key, resolve_template
from taxflow.services.prompt_cache import cacheable_system

# The default ato_response system prompt now lives in the code-owned template
# registry (services/document_templates.py, ATO_RESPONSE_DEFAULT) so a firm can
# override it in Settings; SYSTEM_PROMPT is kept as a re-export for any importer
# and equals the registry default verbatim.
from taxflow.services.document_templates import ATO_RESPONSE_DEFAULT as SYSTEM_PROMPT


class ATOResponseDrafter:
    def __init__(self, llm=None) -> None:
        # LLMPort injected (Task A5); defaults to the configured provider.
        self._llm = llm if llm is not None else providers.get_llm()

    async def draft(
        self,
        classification: dict,
        strategy: dict,
        original_letter: str,
        client_profile: str = "",
        client_id: str | None = None,
    ) -> dict:
        today = date.today().isoformat()
        # Task D1: prepend the advisory client-profile steering string (built from
        # business_type/state/firm_style) so the letter is tuned to the firm's
        # industry/jurisdiction. Advisory only; empty string reproduces the
        # original prompt exactly.
        profile_line = f"{client_profile}\n\n" if client_profile else ""
        user = (
            f"{profile_line}"
            f"ATO Reference: {classification.get('ato_reference')}\n"
            f"Our reference: TF-{today}-{classification.get('ato_reference')}\n"
            f"Letter type: {classification.get('letter_type')}\n"
            f"Response strategy: {strategy['response_strategy']}\n\n"
            f"Original ATO letter:\n{original_letter}"
        )
        # Phase 5: resolve the firm's system prompt for this ATO letter, subtype
        # first (ato_response:{letter_type}) -> base ato_response -> system
        # default. Falls back to the byte-identical default when the firm has no
        # override (or no client_id is threaded, e.g. legacy callers).
        letter_type = classification.get("letter_type")
        if client_id and letter_type:
            system_prompt = resolve_template(client_id, ato_subtype_key(letter_type))
        else:
            system_prompt = SYSTEM_PROMPT
        # The system prompt is large and mostly static; cache it as a stable
        # prefix (Task B1). The per-letter details stay in the user message.
        system_param = cacheable_system(system_prompt)
        result = await self._llm.generate(
            messages=[{"role": "user", "content": user}],
            system=system_param,
            model=providers.resolve_model("draft"),
            max_tokens=1200,
            temperature=0.1,
        )
        letter = result.text
        return {"response_letter": letter}
