"""
One-time setup for the public demo account. Safe to re-run - the client/trial
step upserts, and the query/document/knowledge seeding is skipped if the demo
account already has history (so re-running on every deploy doesn't duplicate
data or burn Anthropic credits repeatedly).

Uses the real agent pipeline against real questions, so the seeded history has
authentic citations against the live knowledge base - not fabricated content.

Run: doppler run --project taxflow --config prd -- \
     uv run python scripts/seed_demo.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from supabase import create_client  # noqa: E402

from taxflow.services.agents.research import ResearchAgent  # noqa: E402
from taxflow.services.agents.verify import VerifyAgent  # noqa: E402
from taxflow.services.knowledge.embedder import embed  # noqa: E402

DEMO_EMAIL = "demo@taxflow.crewcircle.com.au"

SAMPLE_QUESTIONS = [
    "Does the work from home shortcut method still apply and what is the current rate per hour?",
    "Is a company's payment of a shareholder's personal expenses a deemed dividend under Division 7A?",
    "What is the GST treatment of a mixed supply and how is the value apportioned?",
    "What are the requirements for a small business entity to access the 50% CGT discount under Division 152 of ITAA 1997?",
]

FIRM_KNOWLEDGE_SAMPLE = """TaxFlow Demo Firm - Internal Precedent Note

Standard practice for client engagement letters: all new advisory engagements
require a signed scope-of-work letter before research work begins, covering
the specific question(s), the fee basis (fixed or time-based), and a note that
AI-assisted research requires partner review before being relied upon by the
client. Renewed annually for ongoing clients."""


def ensure_demo_client(sb) -> str:
    existing = sb.table("clients").select("id").eq("email", DEMO_EMAIL).execute()
    if existing.data:
        client_id = existing.data[0]["id"]
        sb.table("clients").update({"is_demo": True}).eq("id", client_id).execute()
        print(f"Demo client already exists: {client_id} (is_demo confirmed)")
        return client_id

    result = (
        sb.table("clients")
        .insert(
            {
                "business_name": "TaxFlow Demo Firm",
                "business_type": "accounting",
                "email": DEMO_EMAIL,
                "suburb": "Sydney",
                "state": "NSW",
                "is_demo": True,
                "subscription_status": "active",  # never trial-gated
                "tier": "professional",
            }
        )
        .execute()
    )
    client_id = result.data[0]["id"]
    sb.table("trials").insert(
        {
            "client_id": client_id,
            "trial_status": "active",
            "queries_cap": 100000,
            "docs_cap": 100000,
        }
    ).execute()
    print(f"Created demo client: {client_id}")
    return client_id


async def seed_queries_and_document(sb, client_id: str) -> None:
    research = ResearchAgent()
    verifier = VerifyAgent()

    first_query_id = None
    for question in SAMPLE_QUESTIONS:
        print(f"  researching: {question[:60]}...")
        result = await research.run(question=question, client_id=client_id)
        verification = await verifier.run(
            draft=result["answer"], citations=result["citations"], question=question
        )

        row = (
            sb.table("queries")
            .insert(
                {
                    "client_id": client_id,
                    "user_email": DEMO_EMAIL,
                    "question": question,
                    "module": "research",
                    "status": "completed",
                    "final_answer": result["answer"],
                    "citations": result["citations"],
                    "confidence_score": result["confidence"],
                    "model_used": result["model_used"],
                    "verification_result": verification,
                    "completed_at": "now()",
                }
            )
            .execute()
        )
        if first_query_id is None:
            first_query_id = row.data[0]["id"]
        print(f"    -> {verification.get('overall_status')}, {len(result['citations'])} citations")

    # One generated document, from the first (WFH) question's answer.
    # content_docx is intentionally left unset - download_document() regenerates
    # the file on demand from content_md, so storing bytes here is dead weight.
    first_result = sb.table("queries").select("*").eq("id", first_query_id).execute().data[0]
    sb.table("documents").insert(
        {
            "client_id": client_id,
            "query_id": first_query_id,
            "document_type": "advice_memo",
            "title": "Working From Home Deductions",
            "content_md": first_result["final_answer"],
            "status": "draft",
        }
    ).execute()
    print("  seeded 1 document")


async def seed_firm_knowledge(sb, client_id: str) -> None:
    embedding = await embed(FIRM_KNOWLEDGE_SAMPLE)
    sb.table("firm_knowledge").insert(
        {
            "client_id": client_id,
            "file_name": "engagement-letter-policy.txt",
            "file_type": "txt",
            "content": FIRM_KNOWLEDGE_SAMPLE,
            "embedding": embedding,
        }
    ).execute()
    print("  seeded 1 firm knowledge document")


async def main() -> None:
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    client_id = ensure_demo_client(sb)

    existing_queries = sb.table("queries").select("id").eq("client_id", client_id).limit(1).execute()
    if existing_queries.data:
        print("Demo account already has query history - skipping content seed (idempotent).")
    else:
        print("Seeding demo query history against the live knowledge base...")
        await seed_queries_and_document(sb, client_id)
        await seed_firm_knowledge(sb, client_id)

    print(f"Demo login is ready: POST /auth/demo-login logs visitors into {DEMO_EMAIL}")


if __name__ == "__main__":
    asyncio.run(main())
