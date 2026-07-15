import json

from anthropic import AsyncAnthropic

from taxflow.config import settings
from taxflow.services.prompt_cache import cacheable_system

LETTER_TYPES = [
    "bas_discrepancy",
    "audit_initiation",
    "penalty_notice",
    "garnishee_notice",
    "position_paper",
    "objection_result",
    "ato_debt_notice",
    "payment_plan_request",
    "lodgement_reminder",
    "audit_completion",
    "abn_cancellation",
    "gst_registration",
    "employer_obligations",
    "lifestyle_assets",
    "taxable_payments",
]


class ATOLetterClassifier:
    def __init__(self) -> None:
        self._client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def classify(self, extracted_text: str) -> dict:
        system = (
            "Classify this ATO letter. Return JSON: {'letter_type': '<type from list above>', "
            "'confidence': 0.0-1.0, 'ato_reference': '<reference number from letter>', "
            "'taxpayer_name': '<name as addressed>', "
            "'deadline_days': <integer days from today or null>, "
            "'amount_disputed': <float or null>, "
            "'key_issue': '<one sentence description>'}\n\n"
            f"Valid letter_type values: {LETTER_TYPES}"
        )
        # The system prompt is static (LETTER_TYPES is a constant), so cache it as a
        # stable prefix (Task B1); the per-letter text stays in the user message.
        system_param = cacheable_system(system)
        response = await self._client.messages.create(
            model=settings.ANTHROPIC_HAIKU_MODEL,
            max_tokens=500,
            temperature=0,
            system=system_param,
            messages=[{"role": "user", "content": extracted_text}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        return json.loads(text)
