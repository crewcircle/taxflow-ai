from datetime import date

from anthropic import AsyncAnthropic

from taxflow.config import settings

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
    def __init__(self) -> None:
        self._client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def draft(self, classification: dict, strategy: dict, original_letter: str) -> dict:
        today = date.today().isoformat()
        user = (
            f"ATO Reference: {classification.get('ato_reference')}\n"
            f"Our reference: TF-{today}-{classification.get('ato_reference')}\n"
            f"Letter type: {classification.get('letter_type')}\n"
            f"Response strategy: {strategy['response_strategy']}\n\n"
            f"Original ATO letter:\n{original_letter}"
        )
        # The system prompt is large and fully static; cache it as a stable prefix
        # (Task B1). The per-letter details stay in the user message.
        system_param = (
            [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
            if settings.PROMPT_CACHE_ENABLED
            else SYSTEM_PROMPT
        )
        response = await self._client.messages.create(
            model=settings.ANTHROPIC_HAIKU_MODEL,
            max_tokens=1200,
            temperature=0.1,
            system=system_param,
            messages=[{"role": "user", "content": user}],
        )
        letter = "".join(block.text for block in response.content if block.type == "text")
        return {"response_letter": letter}
