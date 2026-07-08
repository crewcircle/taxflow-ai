import json

from anthropic import AsyncAnthropic

from taxflow.config import settings

SYSTEM_PROMPT = """You are a senior Australian tax lawyer reviewing an AI-drafted advice memo.
Check each factual claim in the draft against the provided source documents.

Return a JSON object with this exact schema:
{
  "overall_status": "verified" | "needs_correction" | "unreliable",
  "issues": [
    {
      "claim": "exact text from draft",
      "issue": "description of problem",
      "severity": "critical" | "warning" | "note",
      "source_says": "what the source actually says",
      "suggested_correction": "how to fix it"
    }
  ],
  "unsupported_claims": ["list of claims with no citation"],
  "overall_confidence": 0.0
}

Severity guide:
- critical: factually wrong based on the sources (wrong rate, wrong section number, wrong test)
- warning: potentially misleading or incomplete
- note: minor stylistic or formatting suggestion

Return ONLY valid JSON. No preamble or explanation."""


def _format_citations(citations: list[dict]) -> str:
    return "\n---\n".join(
        f"Citation: {c.get('citation')}\nContent: {c.get('content') or c.get('excerpt', '')}" for c in citations
    )


class VerifyAgent:
    def __init__(self) -> None:
        self._client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def run(self, draft: str, citations: list[dict], question: str) -> dict:
        user = (
            f"Draft memo to verify:\n{draft}\n\n"
            f"Source documents for verification:\n{_format_citations(citations)}"
        )
        response = await self._client.messages.create(
            model=settings.ANTHROPIC_SONNET_MODEL,
            max_tokens=2000,
            temperature=0,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(block.text for block in response.content if block.type == "text").strip()
        # Models often wrap JSON in ```json fences despite instructions
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text
            text = text.rsplit("```", 1)[0].strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"overall_status": "parse_error", "issues": [], "unsupported_claims": [], "overall_confidence": 0.0}
