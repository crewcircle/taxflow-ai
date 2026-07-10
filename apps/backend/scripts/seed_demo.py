"""
One-time setup for the public demo account. Safe to re-run - each persona's
client/trial step upserts, and its query/document/knowledge seeding is
skipped if that persona already has history (so re-running on every deploy
doesn't duplicate data or burn Anthropic credits repeatedly).

Uses the real agent pipeline against real questions, so the seeded history has
authentic citations against the live knowledge base - not fabricated content.

Seeds three distinct personas so /auth/demo-login can rotate between them.
Each persona is a coherent story that touches every TaxFlow module: research
queries, a generated document, a firm-knowledge upload, and a sample ATO
correspondence thread.

Run: doppler run --project taxflow --config prd -- \
     uv run python scripts/seed_demo.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from supabase import create_client  # noqa: E402

from taxflow.services.agents.draft import DraftAgent  # noqa: E402
from taxflow.services.agents.research import ResearchAgent  # noqa: E402
from taxflow.services.agents.verify import VerifyAgent  # noqa: E402
from taxflow.services.knowledge.embedder import embed  # noqa: E402

PERSONAS = [
    {
        "email": "demo-dental@taxflow.crewcircle.com.au",
        "business_name": "Bayside Dental Group",
        "business_type": "dental",
        "questions": [
            "Can Bayside Dental Group claim the instant asset write-off for a new "
            "$180,000 CBCT scanner purchased this financial year?",
            "Is a car provided to our practice manager for mixed personal and "
            "clinical use subject to FBT, and how do we calculate the taxable "
            "value under the statutory formula method?",
            "The practice's holding entity loaned $95,000 to cover fit-out costs "
            "for a new chair-side unit - does this trigger a deemed dividend "
            "under Division 7A, and how do we structure a complying loan "
            "agreement to avoid it?",
        ],
        "document_title": "Instant Asset Write-Off - CBCT Scanner Purchase",
        "firm_knowledge_title": "equipment-finance-policy.txt",
        "firm_knowledge_content": (
            "Bayside Dental Group - Internal Equipment Finance Policy\n\n"
            "Equipment purchases over $50,000 should be financed via a "
            "commercial chattel mortgage rather than a loan from the holding "
            "entity wherever possible, to avoid Division 7A exposure. Where a "
            "related-entity loan is unavoidable, it must be documented under a "
            "complying Division 7A loan agreement (benchmark interest rate, "
            "maximum term, minimum yearly repayments) before the lodgment day "
            "of the lender's tax return for the income year the loan was made."
        ),
        "ato_letter_type": "fbt_review_notice",
        "ato_response_md": (
            "## Response to ATO FBT Review Notice\n\n"
            "**Re: Fringe Benefits Tax Return - Statutory Formula Car Benefit**\n\n"
            "Bayside Dental Group confirms the practice manager's vehicle was "
            "made available for private use for 312 days of the FBT year. The "
            "taxable value has been calculated using the statutory formula "
            "method at 20% of the car's base value ($42,000), apportioned for "
            "the days available, giving a taxable value of $7,142. This matches "
            "the amount declared on the lodged FBT return. Odometer records and "
            "the vehicle log are attached in support."
        ),
    },
    {
        "email": "demo-property@taxflow.crewcircle.com.au",
        "business_name": "Riverside Property Partners",
        "business_type": "property",
        "questions": [
            "We're selling a commercial development site for $4.2M under the "
            "GST margin scheme - how do we calculate the margin and what "
            "documentation does the ATO require to support it?",
            "Riverside's development is 70% funded by a related offshore "
            "lender - do the thin capitalisation rules under Division 820 "
            "limit our interest deductions this year?",
            "One of our partner entities is a small business entity with "
            "turnover under $2M - does it qualify for the 50% CGT discount "
            "plus the small business 50% reduction on the sale of its "
            "interest in the development?",
        ],
        "document_title": "GST Margin Scheme - Riverside Development Site Sale",
        "firm_knowledge_title": "development-engagement-checklist.txt",
        "firm_knowledge_content": (
            "Riverside Property Partners - Development Project Engagement "
            "Checklist\n\n"
            "At project kickoff, confirm: (1) margin scheme eligibility - the "
            "property must not have been acquired as a fully taxable supply "
            "with GST charged on the full price; (2) a written valuation as at "
            "the relevant acquisition date is obtained if using the valuation "
            "method to calculate the margin; (3) related-party debt funding "
            "above 1.5:1 gearing is flagged for thin capitalisation review "
            "before the interest is claimed as a deduction."
        ),
        "ato_letter_type": "gst_audit_query",
        "ato_response_md": (
            "## Response to ATO GST Audit Query\n\n"
            "**Re: Margin Scheme Calculation - Commercial Development Site**\n\n"
            "The margin has been calculated as the difference between the sale "
            "price of $4.2M and the approved valuation of the site as at 1 July "
            "2001 equivalent acquisition date, being $2.6M, giving a margin of "
            "$1.6M and GST payable of $145,455 (1/11th of the margin). The "
            "supporting valuation report from a qualified valuer and the "
            "original acquisition contract (confirming no GST was charged on "
            "acquisition) are attached."
        ),
    },
    {
        "email": "demo-accounting@taxflow.crewcircle.com.au",
        "business_name": "Chen & Associates",
        "business_type": "accounting",
        "questions": [
            "Does the work from home shortcut method still apply and what is "
            "the current rate per hour?",
            "Our client's family trust wants to make a $150,000 distribution "
            "to an adult beneficiary who then gifts it back to the trust for "
            "the trustee's benefit - does section 100A reimbursement "
            "agreement apply?",
            "A client software company spent $220,000 on eligible R&D "
            "activities this year - what's the R&D tax incentive offset rate "
            "for a company with turnover under $20M, and what records does "
            "the ATO expect to support the claim?",
        ],
        "document_title": "Working From Home Deductions - Fixed Rate Method",
        "firm_knowledge_title": "client-onboarding-checklist.txt",
        "firm_knowledge_content": (
            "Chen & Associates - Client Onboarding & Engagement Checklist\n\n"
            "All new advisory engagements require a signed scope-of-work "
            "letter before research work begins, covering the specific "
            "question(s), the fee basis (fixed or time-based), and a note that "
            "AI-assisted research requires partner review before being relied "
            "upon by the client. Renewed annually for ongoing clients."
        ),
        "ato_letter_type": "trust_distribution_review",
        "ato_response_md": (
            "## Response to ATO Trust Distribution Review\n\n"
            "**Re: Section 100A Reimbursement Agreement Review**\n\n"
            "The $150,000 distribution to the adult beneficiary was applied "
            "directly for that beneficiary's own benefit (repayment of a "
            "personal mortgage), with no agreement, arrangement or "
            "understanding in place for funds to be returned to the trustee or "
            "a related party. As the ordinary family or commercial dealing "
            "exclusion applies and there is no reimbursement agreement, section "
            "100A does not apply to this distribution. Beneficiary bank "
            "statements evidencing the use of funds are attached."
        ),
    },
]


def ensure_demo_client(sb, persona: dict) -> str:
    email = persona["email"]
    existing = sb.table("clients").select("id").eq("email", email).execute()
    if existing.data:
        client_id = existing.data[0]["id"]
        sb.table("clients").update({"is_demo": True}).eq("id", client_id).execute()
        print(f"  {persona['business_name']}: client already exists ({client_id})")
        return client_id

    result = (
        sb.table("clients")
        .insert(
            {
                "business_name": persona["business_name"],
                "business_type": persona["business_type"],
                "email": email,
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
    print(f"  {persona['business_name']}: created client ({client_id})")
    return client_id


async def seed_queries_and_document(sb, client_id: str, persona: dict) -> None:
    research = ResearchAgent()
    drafter = DraftAgent()
    verifier = VerifyAgent()
    email = persona["email"]

    first_query_id = None
    for question in persona["questions"]:
        print(f"    researching: {question[:60]}...")
        result = await research.run(question=question, client_id=client_id)
        draft_result = await drafter.run(
            research_result={"answer": result["answer"], "citations": result["citations"]},
            original_question=question,
            client_id=client_id,
        )
        final_answer = draft_result["draft"]
        verification = await verifier.run(
            draft=final_answer, citations=result["citations"], question=question
        )

        row = (
            sb.table("queries")
            .insert(
                {
                    "client_id": client_id,
                    "user_email": email,
                    "question": question,
                    "module": "research",
                    "status": "completed",
                    "final_answer": final_answer,
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
        print(f"      -> {verification.get('overall_status')}, {len(result['citations'])} citations")

    # One generated document, from the first seeded question's answer.
    # content_docx is intentionally left unset - download_document() regenerates
    # the file on demand from content_md, so storing bytes here is dead weight.
    first_result = sb.table("queries").select("*").eq("id", first_query_id).execute().data[0]
    sb.table("documents").insert(
        {
            "client_id": client_id,
            "query_id": first_query_id,
            "document_type": "advice_memo",
            "title": persona["document_title"],
            "content_md": first_result["final_answer"],
            "status": "draft",
        }
    ).execute()
    print("    seeded 1 document")


async def seed_firm_knowledge(sb, client_id: str, persona: dict) -> None:
    content = persona["firm_knowledge_content"]
    embedding = await embed(content)
    sb.table("firm_knowledge").insert(
        {
            "client_id": client_id,
            "file_name": persona["firm_knowledge_title"],
            "file_type": "txt",
            "content": content,
            "embedding": embedding,
        }
    ).execute()
    print("    seeded 1 firm knowledge document")


def seed_ato_response(sb, client_id: str, persona: dict) -> None:
    sb.table("documents").insert(
        {
            "client_id": client_id,
            "document_type": "ato_response",
            "title": f"ATO Response - {persona['ato_letter_type']}",
            "content_md": persona["ato_response_md"],
            "status": "draft",
        }
    ).execute()
    print("    seeded 1 ATO correspondence document")


async def seed_persona(sb, persona: dict) -> None:
    print(f"{persona['business_name']} ({persona['email']}):")
    client_id = ensure_demo_client(sb, persona)

    existing_queries = sb.table("queries").select("id").eq("client_id", client_id).limit(1).execute()
    if existing_queries.data:
        print("  already has query history - skipping (idempotent).")
    else:
        print("  seeding demo content against the live knowledge base...")
        await seed_queries_and_document(sb, client_id, persona)
        await seed_firm_knowledge(sb, client_id, persona)

    existing_ato = (
        sb.table("documents")
        .select("id")
        .eq("client_id", client_id)
        .eq("document_type", "ato_response")
        .limit(1)
        .execute()
    )
    if existing_ato.data:
        print("  already has ATO correspondence - skipping (idempotent).")
    else:
        seed_ato_response(sb, client_id, persona)


async def main() -> None:
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    for persona in PERSONAS:
        await seed_persona(sb, persona)

    print(f"Demo login is ready: POST /auth/demo-login rotates across {len(PERSONAS)} personas")


if __name__ == "__main__":
    asyncio.run(main())
