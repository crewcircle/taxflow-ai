from taxflow.services.agents.draft import DraftAgent
from taxflow.services.agents.research import ResearchAgent
from taxflow.services.agents.verify import VerifyAgent


class FullPipeline:
    def __init__(self) -> None:
        self.research = ResearchAgent()
        self.draft = DraftAgent()
        self.verify = VerifyAgent()

    async def run(self, question: str, client_id: str) -> dict:
        research_result = await self.research.run(question=question, client_id=client_id)
        draft_result = await self.draft.run(
            research_result=research_result, original_question=question, client_id=client_id
        )
        verification_result = await self.verify.run(
            draft=draft_result["draft"], citations=research_result["citations"], question=question
        )

        return {
            "research": research_result,
            "draft": draft_result,
            "verification": verification_result,
        }
