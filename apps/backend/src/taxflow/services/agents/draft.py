import json
import re

from taxflow import providers
from taxflow.providers import get_relational_data

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
    def __init__(self, llm=None) -> None:
        # LLMPort injected (Task A5); defaults to the configured provider.
        self._llm = llm if llm is not None else providers.get_llm()

    def _load_voice_sample(self, client_id: str) -> str:
        return get_relational_data().clients.get_voice_sample(client_id) or ""

    def _americanism_fix(self, text: str) -> str:
        for us, au in AMERICANISMS.items():
            text = re.sub(us, au, text, flags=re.IGNORECASE)
        return text

    def _sections_present(self, draft: str) -> list[str]:
        return [s for s in REQUIRED_SECTIONS if s in draft.upper()]

    async def _generate(self, system: str, user: str) -> str:
        result = await self._llm.generate(
            messages=[{"role": "user", "content": user}],
            system=system,
            model=providers.resolve_model("draft"),
            max_tokens=2000,
            temperature=0.1,
        )
        return result.text

    async def run(self, research_result: dict, original_question: str, client_id: str) -> dict:
        voice_sample = self._load_voice_sample(client_id)
        voice_instruction = (
            f"The firm describes its own voice like this - match this tone:\n\"{voice_sample}\"\n\n"
            if voice_sample
            else ""
        )

        system = (
            "You are drafting a tax advice memo for an Australian accounting firm.\n"
            f"{voice_instruction}"
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
