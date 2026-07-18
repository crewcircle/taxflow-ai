from datetime import date

from taxflow import providers
from taxflow.config import settings
from taxflow.services.prompt_cache import cacheable_system

SYSTEM_PROMPT = """You are drafting a formal letter to the Australian Taxation Office on behalf of
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
        # The system prompt is large and fully static; cache it as a stable prefix
        # (Task B1). The per-letter details stay in the user message.
        system_param = cacheable_system(SYSTEM_PROMPT)
        result = await self._llm.generate(
            messages=[{"role": "user", "content": user}],
            system=system_param,
            model=settings.ANTHROPIC_HAIKU_MODEL,
            max_tokens=1200,
            temperature=0.1,
        )
        letter = result.text
        return {"response_letter": letter}
