import json

from taxflow import providers
from taxflow.config import settings
from taxflow.ports.llm import StructuredParseError
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
    async def classify(self, extracted_text: str) -> dict:
        # Imported lazily: models.py imports LETTER_TYPES from this module, so a
        # top-level import would be circular.
        from taxflow.services.agents.models import LetterClassification

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
        try:
            result = await providers.get_llm().generate_structured(
                messages=[{"role": "user", "content": extracted_text}],
                system=system_param,
                model=settings.ANTHROPIC_HAIKU_MODEL,
                output_model=LetterClassification,
                max_tokens=500,
                temperature=0,
            )
        except StructuredParseError:
            # Fall back to the tolerant fenced-JSON parse of a plain generation.
            return await self._classify_fallback(system_param, extracted_text)
        return result.model_dump()

    async def _classify_fallback(self, system_param, extracted_text: str) -> dict:
        """Tolerant fallback: plain generation + fenced-JSON stripping (kept from
        the original) when structured validation fails."""
        response = await providers.get_llm().generate(
            messages=[{"role": "user", "content": extracted_text}],
            system=system_param,
            model=settings.ANTHROPIC_HAIKU_MODEL,
            max_tokens=500,
            temperature=0,
        )
        text = (response.text or "").strip()
        # Models often wrap JSON in ```json fences despite instructions.
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text
            text = text.rsplit("```", 1)[0].strip()
        return json.loads(text)
