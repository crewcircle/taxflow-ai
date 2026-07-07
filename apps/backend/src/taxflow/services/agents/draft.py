import json
import re

from anthropic import AsyncAnthropic

from taxflow.config import settings
from taxflow.db import get_supabase_client

REQUIRED_SECTIONS = [
    "SUMMARY",
    "LEGISLATIVE FRAMEWORK",
    "APPLICATION TO FACTS",
    "CONCLUSION AND RECOMMENDED ACTION",
    "IMPORTANT LIMITATIONS",
]

AMERICANISMS = {
    "organization": "organisation",
    "recognize": "recognise",
    "check ": "cheque ",
    "program": "programme",
    "labor": "labour",
    "behavior": "behaviour",
    "center": "centre",
}


class DraftAgent:
    def __init__(self) -> None:
        self._client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    def _load_firm_style(self, client_id: str) -> dict:
        sb = get_supabase_client()
        result = sb.table("clients").select("firm_style").eq("id", client_id).execute()
        if result.data and result.data[0].get("firm_style"):
            return result.data[0]["firm_style"]
        return {}

    def _americanism_fix(self, text: str) -> str:
        for us, au in AMERICANISMS.items():
            text = re.sub(us, au, text, flags=re.IGNORECASE)
        return text

    def _sections_present(self, draft: str) -> list[str]:
        return [s for s in REQUIRED_SECTIONS if s in draft.upper()]

    async def _generate(self, system: str, user: str) -> str:
        response = await self._client.messages.create(
            model=settings.ANTHROPIC_HAIKU_MODEL,
            max_tokens=2000,
            temperature=0.1,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in response.content if block.type == "text")

    async def run(self, research_result: dict, original_question: str, client_id: str) -> dict:
        firm_style = self._load_firm_style(client_id)

        system = (
            "You are drafting a tax advice memo for an Australian accounting firm.\n"
            "Write in the firm's established voice and style.\n"
            f"Firm style profile: {json.dumps(firm_style)}\n\n"
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
        user = (
            f"Draft a tax advice memo based on this research:\n{research_result['answer']}\n\n"
            f"Citations to use:\n{json.dumps(research_result['citations'])}\n\n"
            f"The question was: {original_question}"
        )

        draft = await self._generate(system, user)
        draft = self._americanism_fix(draft)
        sections_present = self._sections_present(draft)

        if len(sections_present) < len(REQUIRED_SECTIONS):
            missing = [s for s in REQUIRED_SECTIONS if s not in sections_present]
            retry_user = user + f"\n\nYour previous draft was missing these required sections: {missing}. Include ALL 5 sections."
            draft = self._americanism_fix(await self._generate(system, retry_user))
            sections_present = self._sections_present(draft)

        return {
            "draft": draft,
            "word_count": len(draft.split()),
            "sections_present": sections_present,
        }
