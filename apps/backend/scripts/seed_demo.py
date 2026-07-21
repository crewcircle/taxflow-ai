"""
One-time setup for the public demo account. Safe to re-run - each persona's
client/trial step upserts, and its query/document/knowledge seeding is
skipped if that persona already has history (so re-running on every deploy
doesn't duplicate data or burn Anthropic credits repeatedly).

Uses the real agent pipeline against real questions, so the seeded history has
authentic citations against the live knowledge base - not fabricated content.

Seeds five distinct personas so /auth/demo-login can rotate between them.
Each persona is a coherent story that touches every TaxFlow module: research
queries, a generated document, a firm-knowledge upload, and a sample ATO
correspondence thread.

Run: doppler run --project taxflow --config prd -- \
     uv run python scripts/seed_demo.py
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from supabase import create_client  # noqa: E402

from taxflow.services.agents.draft import DraftAgent  # noqa: E402
from taxflow.services.agents.research import ResearchAgent  # noqa: E402
from taxflow.services.agents.verify import VerifyAgent  # noqa: E402
from taxflow.services.knowledge.embedder import embed  # noqa: E402

PERSONAS = [
    {
        "email": "demo+coogeebaydental+priya@crewcircle.com.au",
        "business_name": "Coogee Bay Dental Group",
        "business_type": "dental",
        "tagline": (
            "Equipment finance, FBT car benefits, and Division 7A for a "
            "growing dental practice."
        ),
        "description": (
            "A 2-person boutique accounting and bookkeeping practice in "
            "Coogee, Sydney, exclusively serving 12 dental practices "
            "across NSW. Principal accountant Priya Nair plus a bookkeeper "
            "handle day-to-day compliance and equipment/FBT/structuring "
            "advice for dental practice owners."
        ),
        "voice_sample": (
            "We talk to our dental clients like colleagues, not case "
            "numbers. Straight answers, the dollar impact up front, and "
            "we flag anything that needs their accountant's sign-off "
            "before they act on it."
        ),
        "questions": [
            {
                "question": (
                    "Can Coogee Bay Dental Group claim the instant asset write-off for a new "
                    "$180,000 CBCT scanner purchased this financial year?"
                ),
                "days_ago": 18,
                "client_ref": "Smile Bay Dental",
                "topic_tag": "Equipment finance",
                "context_note": (
                    "Client bought a $180k scanner before EOFY - write-off confirmed and "
                    "included in this year's return."
                ),
            },
            {
                "question": (
                    "Is a car provided to our practice manager for mixed personal and "
                    "clinical use subject to FBT, and how do we calculate the taxable "
                    "value under the statutory formula method?"
                ),
                "days_ago": 11,
                "client_ref": "Coastal Family Dentistry",
                "topic_tag": "FBT car benefits",
                "context_note": (
                    "FBT return due this quarter - taxable value confirmed and included "
                    "in the lodged return."
                ),
            },
            {
                "question": (
                    "The practice's holding entity loaned $95,000 to cover fit-out costs "
                    "for a new chair-side unit - does this trigger a deemed dividend "
                    "under Division 7A, and how do we structure a complying loan "
                    "agreement to avoid it?"
                ),
                "days_ago": 3,
                "client_ref": "Smile Bay Dental",
                "topic_tag": "Division 7A",
                "context_note": (
                    "Holding-entity loan flagged in the compliance review - drafting a "
                    "complying Div 7A agreement before lodgment day."
                ),
            },
        ],
        "document_title": "Instant Asset Write-Off - CBCT Scanner Purchase",
        "document_context_note": "Client-ready memo on the scanner write-off - sent for sign-off.",
        "ato_client_ref": "Coastal Family Dentistry",
        "ato_context_note": (
            "ATO flagged the FBT car benefit for review - response drafted, awaiting "
            "partner sign-off before sending."
        ),
        "firm_knowledge_title": "equipment-finance-policy.txt",
        "firm_knowledge_content": (
            "Coogee Bay Dental Group - Internal Equipment Finance Policy\n\n"
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
            "Coogee Bay Dental Group confirms the practice manager's vehicle was "
            "made available for private use for 312 days of the FBT year. The "
            "taxable value has been calculated using the statutory formula "
            "method at 20% of the car's base value ($42,000), apportioned for "
            "the days available, giving a taxable value of $7,142. This matches "
            "the amount declared on the lodged FBT return. Odometer records and "
            "the vehicle log are attached in support."
        ),
    },
    {
        "email": "demo+riversideproperty+david@crewcircle.com.au",
        "business_name": "Riverside Property Partners",
        "business_type": "property",
        "tagline": (
            "GST margin scheme, thin capitalisation, and CGT concessions "
            "for a commercial development."
        ),
        "description": (
            "A 4-person advisory practice in Parramatta, Sydney specialising "
            "in property developers and construction groups: partner David "
            "Okonkwo plus a co-partner and 2 accountants across roughly 8 "
            "active development clients, focused on GST margin scheme, thin "
            "capitalisation, and CGT concession work."
        ),
        "voice_sample": (
            "Our clients are developers under deadline pressure, so we "
            "lead with the answer and the risk, not a legislative essay. "
            "We're direct about what's settled law versus what needs a "
            "private ruling before they sign anything."
        ),
        "questions": [
            {
                "question": (
                    "We're selling a commercial development site for $4.2M under the "
                    "GST margin scheme - how do we calculate the margin and what "
                    "documentation does the ATO require to support it?"
                ),
                "days_ago": 18,
                "client_ref": "Meridian Developments",
                "topic_tag": "GST margin scheme",
                "context_note": (
                    "Site sale settling this quarter - margin confirmed and included "
                    "in the BAS."
                ),
            },
            {
                "question": (
                    "Riverside's development is 70% funded by a related offshore "
                    "lender - do the thin capitalisation rules under Division 820 "
                    "limit our interest deductions this year?"
                ),
                "days_ago": 11,
                "client_ref": "Southbank Construction Group",
                "topic_tag": "Thin capitalisation",
                "context_note": (
                    "Year-end review of the offshore-funded loan - confirmed within "
                    "safe harbour, no action needed."
                ),
            },
            {
                "question": (
                    "One of our partner entities is a small business entity with "
                    "turnover under $2M - does it qualify for the 50% CGT discount "
                    "plus the small business 50% reduction on the sale of its "
                    "interest in the development?"
                ),
                "days_ago": 3,
                "client_ref": "Ashfield Property Holdings",
                "topic_tag": "CGT concessions",
                "context_note": (
                    "Partner considering selling their interest - confirming discount "
                    "eligibility before the sale contract is signed."
                ),
            },
        ],
        "document_title": "GST Margin Scheme - Riverside Development Site Sale",
        "document_context_note": (
            "Client-ready memo on the site sale margin - sent to the partner for review."
        ),
        "ato_client_ref": "Meridian Developments",
        "ato_context_note": (
            "ATO queried the margin calculation on the site sale - response drafted, "
            "awaiting partner sign-off before sending."
        ),
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
        "email": "demo+chenassociates+michael@crewcircle.com.au",
        "business_name": "Chen & Associates",
        "business_type": "accounting",
        "tagline": (
            "Everyday SME advisory: work-from-home deductions, trust "
            "distributions, and the R&D tax incentive."
        ),
        "description": (
            "A 3-person general-practice suburban accounting firm in "
            "Sydney: principal Michael Chen plus 2 accountants, serving "
            "around 40 small business and individual clients on everyday "
            "matters - deductions, trust distributions, and R&D incentive "
            "claims for their small tech/software clients."
        ),
        "voice_sample": (
            "We keep things plain and practical for our clients - most of "
            "them run a business, not a law firm. No jargon we can avoid, "
            "and we always tell them what to actually do, not just what "
            "the law says."
        ),
        "questions": [
            {
                "question": (
                    "Does the work from home shortcut method still apply and what is "
                    "the current rate per hour?"
                ),
                "days_ago": 18,
                "client_ref": "Priya Kapoor",
                "topic_tag": "Work-from-home deductions",
                "context_note": "Client lodging their return this month - rate confirmed and applied.",
            },
            {
                "question": (
                    "Our client's family trust wants to make a $150,000 distribution "
                    "to an adult beneficiary who then gifts it back to the trust for "
                    "the trustee's benefit - does section 100A reimbursement "
                    "agreement apply?"
                ),
                "days_ago": 11,
                "client_ref": "Whitfield Family Trust",
                "topic_tag": "Trust distributions",
                "context_note": (
                    "Trustee flagged an unusual distribution before resolutions were "
                    "finalised - confirmed no reimbursement agreement, resolution can "
                    "proceed."
                ),
            },
            {
                "question": (
                    "A client software company spent $220,000 on eligible R&D "
                    "activities this year - what's the R&D tax incentive offset rate "
                    "for a company with turnover under $20M, and what records does "
                    "the ATO expect to support the claim?"
                ),
                "days_ago": 3,
                "client_ref": "Vantage Software Pty Ltd",
                "topic_tag": "R&D tax incentive",
                "context_note": (
                    "Software client's R&D claim due before the AusIndustry deadline - "
                    "confirming offset rate and required records before lodging."
                ),
            },
        ],
        "document_title": "Working From Home Deductions - Fixed Rate Method",
        "document_context_note": "Client-ready memo on the WFH deduction rate - sent to the client.",
        "ato_client_ref": "Whitfield Family Trust",
        "ato_context_note": (
            "ATO reviewing the trust distribution under s100A - response drafted, "
            "awaiting partner sign-off before sending."
        ),
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
    {
        "email": "demo+enmorehospitality+elena@crewcircle.com.au",
        "business_name": "Enmore Hospitality Accountants",
        "business_type": "hospitality",
        "tagline": (
            "Equipment finance, FBT on staff meals, and GST food "
            "classification for inner-west cafés and restaurants."
        ),
        "description": (
            "A 3-person boutique hospitality accounting practice in "
            "Enmore, Sydney, serving around 25 cafés, restaurants and "
            "small bars across the inner west. Principal Elena Vasquez "
            "plus two accountants handle daily-takings reconciliation, "
            "casual hospitality-award payroll, and the FBT/GST questions "
            "that come with running a kitchen."
        ),
        "voice_sample": (
            "Our clients are flat-out running a service on a Friday "
            "night, not reading tax rulings - we keep advice to what to "
            "do and by when, with the dollar figure up front."
        ),
        "questions": [
            {
                "question": (
                    "Our client is spending $85,000 on new kitchen equipment - "
                    "commercial ovens, fridges, and a POS system - as part of a "
                    "renovation. Does this qualify for the instant asset write-off, "
                    "and does it matter that some items are leased rather than "
                    "purchased outright?"
                ),
                "days_ago": 18,
                "client_ref": "The Local Kitchen",
                "topic_tag": "Equipment finance",
                "context_note": (
                    "Renovation invoices coming through this month - write-off "
                    "eligibility confirmed for the owned items before the return is "
                    "finalised."
                ),
            },
            {
                "question": (
                    "We host a staff dinner on-site every Friday night after close, "
                    "for all kitchen and floor staff - is this exempt from FBT as a "
                    "minor benefit, or does a different exemption apply?"
                ),
                "days_ago": 11,
                "client_ref": "Harbourside Bistro",
                "topic_tag": "FBT car benefits",
                "context_note": (
                    "FBT return being prepared this quarter - exemption basis "
                    "confirmed and documented."
                ),
            },
            {
                "question": (
                    "We're adding packaged takeaway salads and smoothies to the menu "
                    "alongside hot food - which items are GST-free under the food "
                    "classification rules, and which are subject to GST?"
                ),
                "days_ago": 3,
                "client_ref": "Enmore Roasters",
                "topic_tag": "GST",
                "context_note": (
                    "New menu launching next week - GST treatment confirmed per item "
                    "before pricing is finalised."
                ),
            },
        ],
        "document_title": "Instant Asset Write-Off - Kitchen Equipment Renovation",
        "document_context_note": "Client-ready memo on the equipment write-off - sent for sign-off.",
        "ato_client_ref": "Harbourside Bistro",
        "ato_context_note": (
            "ATO flagged the staff-meal FBT exemption for review - response drafted, "
            "awaiting partner sign-off before sending."
        ),
        "firm_knowledge_title": "kitchen-equipment-finance-policy.txt",
        "firm_knowledge_content": (
            "Enmore Hospitality Accountants - Internal Equipment Finance "
            "Policy\n\n"
            "Kitchen equipment purchases over $20,000 should be reviewed for "
            "instant asset write-off eligibility before EOFY, and leased "
            "items should be flagged separately since lease payments (not "
            "the asset itself) are typically the deductible amount. Confirm "
            "each item's business-use percentage before applying the "
            "write-off, particularly for combined front-of-house/kitchen "
            "equipment."
        ),
        "ato_letter_type": "fbt_review_notice",
        "ato_response_md": (
            "## Response to ATO FBT Review Notice\n\n"
            "**Re: Fringe Benefits Tax - Staff Meal Minor Benefits Exemption**\n\n"
            "Harbourside Bistro confirms the Friday staff dinner is provided "
            "on the business premises, on a working day, to current "
            "employees only, and is not provided under a salary sacrifice "
            "arrangement. The value per employee per occasion is under $300 "
            "and the benefit is provided infrequently and irregularly, "
            "consistent with the minor benefits exemption under section "
            "58P. Rosters and the venue's weekly staff-meal cost summary are "
            "attached in support."
        ),
    },
    {
        "email": "demo+nepeantradie+marcus@crewcircle.com.au",
        "business_name": "Nepean Tradie Accountants",
        "business_type": "construction",
        "tagline": (
            "Division 7A director loans, contractor super obligations, and "
            "the GST margin scheme for Western Sydney builders and tradies."
        ),
        "description": (
            "A 3-person practice in Penrith, Sydney, serving around 30 "
            "builders, tradies and small construction companies across "
            "Western Sydney. Principal Marcus Webb plus two accountants "
            "handle everyday compliance plus the trickier structuring "
            "questions that come with project-based work and director "
            "loans."
        ),
        "voice_sample": (
            "Our clients are on job sites all day, not in front of a "
            "screen - we keep it short, tell them exactly what to do "
            "next, and flag anything that needs a lawyer or a private "
            "ruling before they act."
        ),
        "questions": [
            {
                "question": (
                    "Our building company director took a $60,000 advance from the "
                    "company to help fund a deposit on his own home - is this a "
                    "Division 7A loan, and what do we need to do before the company's "
                    "lodgment day to avoid a deemed dividend?"
                ),
                "days_ago": 18,
                "client_ref": "Western Build Co",
                "topic_tag": "Division 7A",
                "context_note": (
                    "Advance made mid-year - complying loan agreement being drafted "
                    "before lodgment day."
                ),
            },
            {
                "question": (
                    "We engage several subcontractors on our residential building "
                    "sites who provide their own tools and invoice us via ABN - could "
                    "the ATO reclassify them as employees for superannuation "
                    "guarantee purposes, and what factors matter most?"
                ),
                "days_ago": 11,
                "client_ref": "Hawkesbury Trade Services",
                "topic_tag": "Superannuation",
                "context_note": (
                    "Contractor arrangements reviewed ahead of the super guarantee "
                    "due date - classification confirmed as genuine contractors."
                ),
            },
            {
                "question": (
                    "One of our builder clients is completing a small 3-lot "
                    "subdivision and selling the new townhouses - does the GST margin "
                    "scheme apply to reduce GST payable on the sales, and what "
                    "records do we need to support the valuation?"
                ),
                "days_ago": 3,
                "client_ref": "Nepean Constructions Pty Ltd",
                "topic_tag": "GST margin scheme",
                "context_note": (
                    "First townhouse settling next month - margin scheme eligibility "
                    "and valuation confirmed before the BAS is lodged."
                ),
            },
        ],
        "document_title": "Division 7A Director Loan - Complying Agreement Advice",
        "document_context_note": "Client-ready memo on the director loan - sent to the director for sign-off.",
        "ato_client_ref": "Hawkesbury Trade Services",
        "ato_context_note": (
            "ATO reviewing subcontractor super guarantee classification - response "
            "drafted, awaiting partner sign-off before sending."
        ),
        "firm_knowledge_title": "subcontractor-engagement-checklist.txt",
        "firm_knowledge_content": (
            "Nepean Tradie Accountants - Subcontractor Engagement "
            "Checklist\n\n"
            "Before treating a worker as a contractor rather than an "
            "employee, confirm: (1) they can subcontract or delegate the "
            "work to someone else; (2) they provide and maintain their own "
            "tools and equipment; (3) they bear commercial risk for "
            "defective or late work; (4) they are paid for a result, not by "
            "time worked. Where any factor is unclear, default to treating "
            "the worker as an employee for superannuation guarantee "
            "purposes until reviewed."
        ),
        "ato_letter_type": "super_guarantee_review",
        "ato_response_md": (
            "## Response to ATO Superannuation Guarantee Review\n\n"
            "**Re: Subcontractor Classification - Superannuation Guarantee "
            "Obligations**\n\n"
            "Hawkesbury Trade Services confirms its site subcontractors each "
            "hold their own ABN, supply and maintain their own hand tools "
            "and power tools, carry their own public liability insurance, "
            "and are engaged and paid per completed stage of work rather "
            "than by the hour. Each subcontractor has also previously "
            "worked for other building companies during the review period. "
            "On this basis they are genuine contractors, not employees, and "
            "no superannuation guarantee shortfall arises. Subcontractor "
            "agreements, insurance certificates and invoices are attached "
            "in support."
        ),
    },
]


def ensure_demo_client(sb, persona: dict) -> str:
    email = persona["email"]
    existing = sb.table("clients").select("id").eq("email", email).execute()
    if existing.data:
        client_id = existing.data[0]["id"]
        sb.table("clients").update(
            {
                "is_demo": True,
                "demo_tagline": persona["tagline"],
                "demo_description": persona["description"],
                "voice_sample": persona["voice_sample"],
            }
        ).eq("id", client_id).execute()
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
                "demo_tagline": persona["tagline"],
                "demo_description": persona["description"],
                "voice_sample": persona["voice_sample"],
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


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


async def seed_queries_and_document(sb, client_id: str, persona: dict) -> None:
    research = ResearchAgent()
    drafter = DraftAgent()
    verifier = VerifyAgent()
    email = persona["email"]

    first_query_id = None
    first_days_ago = None
    first_answer = None
    first_citations = None
    for item in persona["questions"]:
        question = item["question"]
        print(f"    researching: {question[:60]}...")
        result = await research.run(question=question, client_id=client_id)
        # The raw research answer is what's shown and stored as-is - matches
        # production, which no longer forces every chat answer into a formal
        # memo. Verification checks this same answer, not a reformatted one.
        final_answer = result["answer"]
        verification = await verifier.run(
            draft=final_answer, citations=result["citations"], question=question
        )

        timestamp = _days_ago(item["days_ago"])
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
                    "client_ref": item["client_ref"],
                    "topic_tag": item["topic_tag"],
                    "context_note": item["context_note"],
                    "created_at": timestamp,
                    "completed_at": timestamp,
                }
            )
            .execute()
        )
        if first_query_id is None:
            first_query_id = row.data[0]["id"]
            first_days_ago = item["days_ago"]
            first_answer = final_answer
            first_citations = result["citations"]
        print(f"      -> {verification.get('overall_status')}, {len(result['citations'])} citations")

    # One generated document: the first seeded question's answer, reformatted
    # into the firm's 5-section advice memo (this is the one place that
    # formatting is used - matches production, where it only applies when
    # explicitly saving a research answer as an advice_memo document), dated
    # a day after its source question. content_docx is intentionally left
    # unset - download_document() regenerates the file on demand from
    # content_md.
    draft_result = await drafter.run(
        research_result={"answer": first_answer, "citations": first_citations},
        original_question=persona["questions"][0]["question"],
        client_id=client_id,
    )
    sb.table("documents").insert(
        {
            "client_id": client_id,
            "query_id": first_query_id,
            "document_type": "advice_memo",
            "title": persona["document_title"],
            "content_md": draft_result["draft"],
            "client_ref": persona["questions"][0]["client_ref"],
            "context_note": persona["document_context_note"],
            "status": "draft",
            "created_at": _days_ago(max(first_days_ago - 1, 0)),
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
            "client_ref": persona["ato_client_ref"],
            "context_note": persona["ato_context_note"],
            "status": "draft",
            "created_at": _days_ago(6),
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
